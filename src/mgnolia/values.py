"""Values produced and consumed during validation."""

from __future__ import annotations

from typing import Generic, TypeVar, cast


T = TypeVar("T")
_UNSET = object()


class Value(Generic[T]):
    """A named value populated by a validation rule."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._value: T | object = _UNSET

    def set(self, value: T) -> None:
        self._value = value

    def clear(self) -> None:
        self._value = _UNSET

    def ref(self) -> Ref[T]:
        return Ref(self)

    def __deepcopy__(self, memo: dict[int, object]) -> Value[T]:
        return self


class Ref(Generic[T]):
    """A reference to a value produced earlier in validation."""

    def __init__(self, value: Value[T]) -> None:
        self.value = value

    def resolve(self) -> T:
        if self.value._value is _UNSET:
            raise RuntimeError(
                f"Value {self.value.name!r} has not been produced yet; "
                "declare its producing node before its consumer"
            )
        return cast(T, self.value._value)

    def __str__(self) -> str:
        return str(self.resolve())


def resolve(value: T | Ref[T]) -> T:
    """Resolve a reference, or return a literal value unchanged."""

    if isinstance(value, Ref):
        return cast(T, value.resolve())
    return cast(T, value)
