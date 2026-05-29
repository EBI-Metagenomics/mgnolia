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
