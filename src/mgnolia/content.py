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

from mgnolia.errors import ContentSchemaError, ContentValidationError, FileEmptyError

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
