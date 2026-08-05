"""Schema node classes (Dir, File) and root Schema for filesystem validation."""

from __future__ import annotations

import abc
from glob import has_magic
from itertools import product
from os import PathLike
from pathlib import Path
from typing import Optional

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
from mgnolia.values import Ref, Value, resolve

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


class Node(NodeBase, abc.ABC):
    """Common configuration for typed public models."""

    min_matches: NonNegativeInt | Ref[int] = 1
    max_matches: PositiveInt | Ref[int] | None = 1
    output: Value[int] | None = None

    @abc.abstractmethod
    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]: ...

    @abc.abstractmethod
    def validate_content(self) -> list[ContentValidationError]: ...

    @abc.abstractmethod
    def _missing_error(self, path: Path) -> StructureValidationError: ...

    def _validate_match_count(
        self, parent_path: Path, matches: list[Path]
    ) -> list[StructureValidationError]:
        num_of_matches = len(matches)
        if self.output is not None:
            self.output.set(num_of_matches)
        min_matches = resolve(self.min_matches)
        max_matches = (
            resolve(self.max_matches) if self.max_matches is not None else None
        )

        if max_matches is not None and max_matches < min_matches:
            raise RuntimeError("resolved max_matches is less than min_matches")

        if num_of_matches < min_matches:
            if self.path_is_glob:
                return [MinMatchError(self, parent_path / self.path)]
            return [self._missing_error(parent_path / self.path)]

        if max_matches is not None and num_of_matches > max_matches:
            return [MaxMatchError(self, parent_path / self.path)]

        return []

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
        cls, value: PositiveInt | Ref[int] | None, info: ValidationInfo
    ) -> PositiveInt | Ref[int] | None:
        min_matches = info.data.get("min_matches", 1)

        if (
            value is not None
            and not isinstance(value, Ref)
            and not isinstance(min_matches, Ref)
            and value < min_matches
        ):
            raise ValueError("max_matches must be greater than or equal to min_matches")

        return value


class Dir(Node):
    """Declarative directory node."""

    children: list["Dir | File"] = Field(default_factory=list)

    _matched: bool | None = PrivateAttr(default=None)
    _resolved_children: list["Dir | File"] = PrivateAttr(default_factory=list)

    def _missing_error(self, path: Path) -> StructureValidationError:
        return DirectoryMissingError(self, path)

    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]:
        parent = Path(parent_path)
        matches = list(parent.glob(str(self.path)))
        errors = self._validate_match_count(parent, matches)
        self._resolved_children = []
        if errors:
            self._matched = False
            return errors
        self._matched = True
        child_errors: list[StructureValidationError] = []
        # Clone children per matched directory so each match owns its own
        # validation state. Without this, declared children are shared
        # across glob matches and their private attrs (e.g. File's
        # `_resolved_paths`) get overwritten on every iteration, so content
        # rules only ever run against the last matched directory.
        for child, dir_path in product(self.children, matches):
            resolved_child = child.model_copy(deep=True)
            child_errors.extend(resolved_child.validate_structure(dir_path))
            self._resolved_children.append(resolved_child)
        return child_errors

    def validate_content(self) -> list[ContentValidationError]:
        if self._matched is None:
            raise RuntimeError(
                "validate_structure() must be called before validate_content(). "
                "Use Schema.validate_all() to run both in the correct order."
            )
        if not self._matched:
            return []
        errors: list[ContentValidationError] = []
        for child in self._resolved_children:
            errors.extend(child.validate_content())
        return errors


class File(Node):
    """Declarative file node."""

    content_rules: list[ContentRule] = Field(default_factory=list)

    _resolved_paths: list[Path] | None = PrivateAttr(default=None)

    def _missing_error(self, path: Path) -> StructureValidationError:
        return FileMissingError(self, path)

    def validate_structure(
        self, parent_path: PathOrStr
    ) -> list[StructureValidationError]:
        parent = Path(parent_path)
        matches = list(parent.glob(str(self.path)))
        errors = self._validate_match_count(parent, matches)
        if errors:
            self._resolved_paths = []
            return errors
        self._resolved_paths = [p.resolve() for p in matches]
        return []

    def validate_content(self) -> list[ContentValidationError]:
        if self._resolved_paths is None:
            raise RuntimeError(
                "validate_structure() must be called before validate_content(). "
                "Use Schema.validate_all() to run both in the correct order."
            )
        errors: list[ContentValidationError] = []

        for path, rule in product(self._resolved_paths, self.content_rules):
            content_errors = rule.validate(self, path)
            errors.extend(content_errors)

        return errors


class Schema(NodeBase):
    path: PathOrStr = Field(default_factory=Path.cwd)
    children: list["Dir | File"] = Field(default_factory=list)

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
        self._reset_outputs(self.children)

        for child in self.children:
            structure_errors = child.validate_structure(normalized_root_path)
            self._errors.extend(structure_errors)

            content_errors = child.validate_content()
            self._errors.extend(content_errors)

        return not self._errors

    @classmethod
    def _reset_outputs(cls, nodes: list[Dir | File]) -> None:
        for node in nodes:
            if node.output is not None:
                node.output.clear()
            if isinstance(node, File):
                for rule in node.content_rules:
                    rule.reset()
            else:
                cls._reset_outputs(node.children)
