"""Validation error types for structure and content failures."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal
from pandera.errors import SchemaError

if TYPE_CHECKING:
    from mgnolia.schema import Node


class ValidationError:
    message: str = "Validation Error"
    error_type: Literal["structure", "content"]

    def __init__(self, node: Node, path: Path) -> None:
        self.node = node
        self.path = path

    def get_message(self) -> str:
        return self.message

    def __str__(self) -> str:
        return f"{self.path} {self.get_message()}"


class StructureValidationError(ValidationError):
    error_type = "structure"


class ContentValidationError(ValidationError):
    error_type = "content"


# Structure errors


class FileMissingError(StructureValidationError):
    message = "File missing"


class DirectoryMissingError(StructureValidationError):
    message = "Directory missing"


class MinMatchError(StructureValidationError):
    def get_message(self) -> str:
        return f"Too few matches. Expected at least {self.node.min_matches}"


class MaxMatchError(StructureValidationError):
    def get_message(self) -> str:
        return f"Too many matches. Expected at most {self.node.max_matches}"


# Content errors
class NotAFileError(ContentValidationError):
    message = "Not a file"


class FileEmptyError(ContentValidationError):
    message = "File is empty"


class ContentSchemaError(ContentValidationError):
    def __init__(self, node: Node, path: Path, schema_error: SchemaError) -> None:
        super().__init__(node, path)
        self.schema_error = schema_error

    def get_message(self) -> str:
        if self.schema_error.failure_cases is None:
            return "Unknown schema error"

        failure_cases = self.schema_error.failure_cases
        if "index" in failure_cases.columns:
            indices = ", ".join(str(i) for i in failure_cases["index"])
            return f"Schema error at rows: {indices}"

        return f"Schema validation failed with {len(failure_cases)} failure case(s)"


class ParquetSchemaMismatchError(ContentValidationError):
    def __init__(
        self,
        node: Node,
        path: Path,
        missing: set[str],
        extra: set[str],
        wrong_dtype: dict[str, tuple[object, object]],
    ) -> None:
        super().__init__(node, path)
        self.missing = missing
        self.extra = extra
        self.wrong_dtype = wrong_dtype

    def get_message(self) -> str:
        return (
            f"Parquet schema mismatch: missing={self.missing}, "
            f"extra={self.extra}, wrong_dtype={self.wrong_dtype}"
        )


class RowCountError(ContentValidationError):
    def __init__(
        self,
        node: Node,
        path: Path,
        actual: int,
        *,
        exact: int | None = None,
        min: int | None = None,
        max: int | None = None,
    ) -> None:
        super().__init__(node, path)
        self.actual = actual
        self.exact = exact
        self.min = min
        self.max = max

    def get_message(self) -> str:
        if self.exact is not None:
            return f"Row count {self.actual} != expected {self.exact}"
        bounds = []
        if self.min is not None:
            bounds.append(f"min={self.min}")
        if self.max is not None:
            bounds.append(f"max={self.max}")
        return f"Row count {self.actual} out of bounds ({', '.join(bounds)})"


class NotSortedError(ContentValidationError):
    def __init__(self, node: Node, path: Path, column: str) -> None:
        super().__init__(node, path)
        self.column = column

    def get_message(self) -> str:
        return f"Not sorted ascending by {self.column!r}"
