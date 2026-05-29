"""Schema node classes (Dir, File) and root Schema for filesystem validation."""

from __future__ import annotations

from glob import has_magic
from itertools import product
from os import PathLike
from pathlib import Path
from typing import Iterable, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    PrivateAttr,
    ValidationInfo,
    field_validator,
)

from mgnolia.content import ContentRule
from mgnolia.errors import (
    ContentValidationError,
    DirectoryMissingError,
    FileMissingError,
    MaxMatchError,
    MinMatchError,
    StructureValidationError,
    ValidationError,
)

type PathOrStr = str | PathLike[str] | Path


class NodeBase(BaseModel):
    path: PathOrStr
    description: Optional[str] = None

    @property
    def path_is_glob(self) -> bool:
        return has_magic(str(self.path))

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        arbitrary_types_allowed=True,
    )


class Node(NodeBase):
    """Common configuration for typed public models."""

    min_matches: NonNegativeInt = 1
    max_matches: Optional[PositiveInt] = 1

    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]:
        return NotImplemented

    def validate_content(self) -> list[ContentValidationError]:
        return NotImplemented

    @field_validator("path")
    @classmethod
    def validate_relative_and_clean_path(
        cls, value: str | PathLike[str] | Path
    ) -> Path:
        path = Path(value)

        if path.is_absolute():
            raise ValueError("path must be relative")

        if "." in path.parts or ".." in path.parts:
            raise ValueError("path must not contain '.' or '..' segments")

        return path

    @field_validator("max_matches")
    @classmethod
    def validate_max_matches(
        cls, value: Optional[PositiveInt], info: ValidationInfo
    ) -> Optional[PositiveInt]:
        min_matches = info.data.get("min_matches", 1)

        if value is not None and value < min_matches:
            raise ValueError("max_matches must be greater than or equal to min_matches")

        return value


class Dir(Node):
    """Declarative directory node."""

    children: Iterable["Dir | File"] = Field(default_factory=list)

    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]:
        normalized_parent_path = Path(parent_path)
        matches = list(normalized_parent_path.glob(str(self.path)))
        num_of_matches = len(matches)

        if num_of_matches < self.min_matches:
            if self.path_is_glob:
                return [MinMatchError(self, normalized_parent_path / self.path)]

            return [DirectoryMissingError(self, normalized_parent_path / self.path)]

        if self.max_matches is not None and num_of_matches > self.max_matches:
            return [MaxMatchError(self, normalized_parent_path / self.path)]

        errors: list[StructureValidationError] = []

        for child, dir_path in product(self.children, matches):
            child_errors = child.validate_structure(dir_path)
            errors.extend(child_errors)

        return errors

    def validate_content(self) -> list[ContentValidationError]:
        errors: list[ContentValidationError] = []

        for child in self.children:
            child_errors = child.validate_content()
            errors.extend(child_errors)

        return errors


class File(Node):
    """Declarative file node."""

    content_rules: list[ContentRule] = Field(default_factory=list)

    _resolved_paths: list[Path] = PrivateAttr(default_factory=list)

    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]:
        normalized_parent_path = Path(parent_path)
        matches = list(normalized_parent_path.glob(str(self.path)))
        num_of_matches = len(matches)

        if num_of_matches < self.min_matches:
            if self.path_is_glob:
                return [MinMatchError(self, normalized_parent_path / self.path)]

            return [FileMissingError(self, normalized_parent_path / self.path)]

        if self.max_matches is not None and num_of_matches > self.max_matches:
            return [MaxMatchError(self, normalized_parent_path / self.path)]

        self._resolved_paths = [path.resolve() for path in matches]

        return []

    def validate_content(self) -> list[ContentValidationError]:
        errors: list[ContentValidationError] = []

        for rule, path in product(self.content_rules, self._resolved_paths):
            content_errors = rule.validate(self, path)
            errors.extend(content_errors)

        return errors


class Schema(NodeBase):
    path: PathOrStr = Field(default_factory=Path.cwd)
    children: Iterable["Dir | File"] = Field(default_factory=list)

    _errors: list[ValidationError] = PrivateAttr(default_factory=list)

    @property
    def errors(self) -> list[ValidationError]:
        return self._errors

    @property
    def ok(self) -> bool:
        return not self._errors

    def validate_all(self, root_path: Optional[PathOrStr]) -> bool:
        normalized_root_path = Path(root_path or self.path).resolve()
        self._errors.clear()

        for child in self.children:
            structure_errors = child.validate_structure(normalized_root_path)
            self._errors.extend(structure_errors)

            content_errors = child.validate_content()
            self._errors.extend(content_errors)

        return not self._errors
