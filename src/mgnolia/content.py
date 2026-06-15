"""Abstract base and built-in content validation rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Type

import pandera.polars as pa
import polars as pl
from pandera.engines.polars_engine import PydanticModel
from pandera.errors import SchemaErrors
from pydantic import BaseModel

from mgnolia.errors import (
    ContentSchemaError,
    ContentValidationError,
    FileEmptyError,
    NotSortedError,
    ParquetSchemaMismatchError,
    RowCountError,
)

if TYPE_CHECKING:
    from mgnolia.schema import Node


class ContentRule(ABC):
    @abstractmethod
    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        pass


class FileNotEmptyRule(ContentRule):
    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        if path.stat().st_size == 0:
            return [FileEmptyError(node, path)]

        return []


class CSVSchemaRule(ContentRule):
    def __init__(self, schema: Type[BaseModel]) -> None:
        super().__init__()

        self.schema = schema
        self.dataframe_schema = pa.DataFrameSchema(
            dtype=PydanticModel(self.schema), coerce=True
        )

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        lf = pl.scan_csv(path)

        try:
            self.dataframe_schema.validate(lf, lazy=True).collect()
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

    def __init__(self, schema: dict[str, pl.DataType]) -> None:
        super().__init__()
        self.schema = schema

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        actual = dict(pl.scan_parquet(path).collect_schema())
        missing = {c for c in self.schema if c not in actual}
        extra = {c for c in actual if c not in self.schema}
        wrong_dtype = {
            c: (self.schema[c], actual[c])
            for c in self.schema
            if c in actual and actual[c] != self.schema[c]
        }
        if not (missing or extra or wrong_dtype):
            return []
        return [ParquetSchemaMismatchError(node, path, missing, extra, wrong_dtype)]


class RowCountRule(ContentRule):
    """
    Assert a parquet file's row count satisfies a bound.

    One of `exact`, `min`, or `max` (or both `min` and `max`) must be
    given. Row counts come from parquet metadata — this is a free check.
    """

    def __init__(
        self,
        *,
        exact: int | None = None,
        min: int | None = None,
        max: int | None = None,
    ) -> None:
        super().__init__()
        if exact is None and min is None and max is None:
            raise ValueError("RowCountRule requires at least one of exact, min, max")
        if exact is not None and (min is not None or max is not None):
            raise ValueError("RowCountRule: exact cannot be combined with min/max")
        if min is not None and max is not None and min > max:
            raise ValueError(f"RowCountRule: min ({min}) cannot exceed max ({max})")
        self.exact = exact
        self.min = min
        self.max = max

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        actual = pl.scan_parquet(path).select(pl.len()).collect().item()
        if self.exact is not None:
            if actual == self.exact:
                return []
            return [RowCountError(node, path, actual, exact=self.exact)]
        if self.min is not None and actual < self.min:
            return [RowCountError(node, path, actual, min=self.min, max=self.max)]
        if self.max is not None and actual > self.max:
            return [RowCountError(node, path, actual, min=self.min, max=self.max)]
        return []


class SortedRule(ContentRule):
    """
    Assert a parquet column is sorted ascending.

    Streaming scan of one column — cheap on narrow integer keys, expensive
    on TB-scale files. The `deep` kwarg gates the scan, when False the
    rule no-ops. Placeholder for a future framework-level cost-tier mechanism.
    """

    def __init__(self, column: str, *, deep: bool = False) -> None:
        super().__init__()
        self.column = column
        self.deep = deep

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        if not self.deep:
            return []
        ok = (
            pl.scan_parquet(path)
            .select((pl.col(self.column).diff() >= 0).all())
            .collect()
            .item()
        )
        if ok:
            return []
        return [NotSortedError(node, path, self.column)]
