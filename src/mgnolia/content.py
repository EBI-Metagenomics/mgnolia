"""Abstract base and built-in content validation rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Type

import pandera.polars as pa
import polars as pl
from pandera.engines.polars_engine import PydanticModel
from pandera.errors import SchemaErrors
from pydantic import BaseModel

from mgnolia.errors import (
    ContentSchemaError,
    ContentValidationError,
    FileEmptyError,
    MissingColumnError,
    NotSortedError,
    ParquetSchemaMismatchError,
    RowCountError,
)
from mgnolia.values import Ref, Value, resolve

if TYPE_CHECKING:
    from mgnolia.schema import Node


class ContentRule(ABC):
    output: Value[Any] | None = None

    def __init__(self, output: Value[Any] | None = None) -> None:
        self.output = output

    def reset(self) -> None:
        """Clear results retained from an earlier schema validation."""

        if self.output is not None:
            self.output.clear()

    @abstractmethod
    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        pass


class FileNotEmptyRule(ContentRule):
    def __init__(self, *, output: Value[int] | None = None) -> None:
        super().__init__(output)

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        size = path.stat().st_size
        if self.output is not None:
            self.output.set(size)
        if size == 0:
            return [FileEmptyError(node, path)]

        return []


class CSVSchemaRule(ContentRule):
    def __init__(
        self,
        schema: Type[BaseModel] | Ref[Type[BaseModel]],
        *,
        output: Value[dict[str, pl.DataType]] | None = None,
    ) -> None:
        super().__init__(output)

        self.schema = schema

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        lf = pl.scan_csv(path)
        if self.output is not None:
            self.output.set(dict(lf.collect_schema()))
        dataframe_schema = pa.DataFrameSchema(
            dtype=PydanticModel(resolve(self.schema)), coerce=True
        )

        try:
            dataframe_schema.validate(lf, lazy=True).collect()
        except SchemaErrors as e:
            return [ContentSchemaError(node, path, error) for error in e.schema_errors]

        return []


class ParquetSchemaRule(ContentRule):
    """
    Assert a parquet file's columns and dtypes match an expected polars schema.

    Takes a `dict[str, pl.DataType]` rather than a Pydantic model (as
    `CSVSchemaRule` does) because parquet stores its schema in the file
    footer with full polars-level dtype precision (Int8 vs Int64, Decimal
    precision/scale, timezone-aware Datetime, List/Struct inners). A
    Pydantic model would have to round-trip through pandera's engine and
    lose that precision. This rule is a pure structural check; for
    row-level value constraints use a separate pandera-based rule.
    """

    def __init__(
        self,
        schema: dict[str, pl.DataType] | Ref[dict[str, pl.DataType]],
        *,
        output: Value[dict[str, pl.DataType]] | None = None,
    ) -> None:
        super().__init__(output)
        self.schema = schema

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        expected = resolve(self.schema)
        actual = dict(pl.scan_parquet(path).collect_schema())
        if self.output is not None:
            self.output.set(actual)
        missing = {c for c in expected if c not in actual}
        extra = {c for c in actual if c not in expected}
        wrong_dtype: dict[str, tuple[object, object]] = {
            c: (expected[c], actual[c])
            for c in expected
            if c in actual and actual[c] != expected[c]
        }
        if not (missing or extra or wrong_dtype):
            return []
        error: ContentValidationError = ParquetSchemaMismatchError(
            node, path, missing, extra, wrong_dtype
        )
        return [error]


class RowCountRule(ContentRule):
    """
    Assert a parquet file's row count satisfies a bound.

    One of `exact`, `min`, or `max` (or both `min` and `max`) must be
    given. Row counts come from parquet metadata — this is a free check.
    """

    def __init__(
        self,
        *,
        exact: int | Ref[int] | None = None,
        min: int | Ref[int] | None = None,
        max: int | Ref[int] | None = None,
        output: Value[int] | None = None,
    ) -> None:
        super().__init__(output)
        if exact is None and min is None and max is None:
            raise ValueError("RowCountRule requires at least one of exact, min, max")
        if exact is not None and (min is not None or max is not None):
            raise ValueError("RowCountRule: exact cannot be combined with min/max")
        if (
            min is not None
            and max is not None
            and not isinstance(min, Ref)
            and not isinstance(max, Ref)
            and min > max
        ):
            raise ValueError(f"RowCountRule: min ({min}) cannot exceed max ({max})")
        self.exact = exact
        self.min = min
        self.max = max
        self.output = output

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        actual = pl.scan_parquet(path).select(pl.len()).collect().item()
        if self.output is not None:
            self.output.set(actual)
        exact = resolve(self.exact) if self.exact is not None else None
        minimum = resolve(self.min) if self.min is not None else None
        maximum = resolve(self.max) if self.max is not None else None
        if minimum is not None and maximum is not None and minimum > maximum:
            raise RuntimeError("resolved RowCountRule min is greater than max")
        if exact is not None:
            if actual == exact:
                return []
            return [RowCountError(node, path, actual, exact=exact)]
        if minimum is not None and actual < minimum:
            return [RowCountError(node, path, actual, min=minimum, max=maximum)]
        if maximum is not None and actual > maximum:
            return [RowCountError(node, path, actual, min=minimum, max=maximum)]
        return []


class SortedRule(ContentRule):
    """
    Assert a parquet column is sorted in the given order.

    Streaming scan of one column — cheap on narrow integer keys, expensive
    on TB-scale files.
    """

    def __init__(
        self,
        column: str | Ref[str],
        *,
        order: Literal["asc", "desc"] | Ref[Literal["asc", "desc"]] = "asc",
        output: Value[tuple[object, object]] | None = None,
    ) -> None:
        super().__init__(output)
        self.column = column
        self.order: Literal["asc", "desc"] | Ref[Literal["asc", "desc"]] = order

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        column = resolve(self.column)
        order = resolve(self.order)
        col = pl.col(column)
        next_val = col.shift(-1)
        check = (col <= next_val) if order == "asc" else (col >= next_val)
        try:
            ok, minimum, maximum = (
                pl.scan_parquet(path)
                .select(
                    check.all().alias("_sorted"),
                    col.min().alias("_min"),
                    col.max().alias("_max"),
                )
                .collect()
                .row(0)
            )
        except pl.exceptions.ColumnNotFoundError:
            return [MissingColumnError(node, path, column)]
        if self.output is not None:
            self.output.set((minimum, maximum))
        if ok:
            return []
        return [NotSortedError(node, path, column, order)]
