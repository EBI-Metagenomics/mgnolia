# Design: mgnolia Maintainability Improvements

## Context

mgnolia is a small Python library (~326 LOC) for declarative filesystem structure and content validation. A maintainability analysis identified 7 concrete issues: a DRY violation in the core node classes, a hidden ordering contract between validation steps, incorrect use of `NotImplemented`, two typos in error messages, absent documentation, and a misleading example file. This spec covers the design for all 7 fixes.

---

## Changes

### 1. Extract duplicate validation logic (DRY fix) — `schema.py`

**Problem:** `Dir.validate_structure()` and `File.validate_structure()` share ~15 lines of identical match-count logic (glob, min/max check, error construction). The only difference is which missing-error class each uses (`DirectoryMissingError` vs `FileMissingError`).

**Design — Option A: `_validate_match_count` + abstract `_missing_error`**

Add to `Node`:
- `_missing_error(path: Path) -> StructureValidationError` — `@abstractmethod`, returns the appropriate missing-error for the subclass
- `_validate_match_count(parent_path: Path, matches: list[Path]) -> list[StructureValidationError]` — concrete shared method; checks min/max/glob and calls `self._missing_error`

Make `Node(NodeBase, abc.ABC)` (add `abc.ABC` to the MRO — confirmed valid with Pydantic v2 via context7 docs).

Remove `return NotImplemented` stubs and mark `validate_structure` and `validate_content` as `@abstractmethod` on `Node`.

**Result:**

`Dir.validate_structure`:
```python
def validate_structure(self, parent_path):
    parent = Path(parent_path)
    matches = list(parent.glob(str(self.path)))
    errors = self._validate_match_count(parent, matches)
    if errors:
        return errors
    child_errors: list[StructureValidationError] = []
    for child, dir_path in product(self.children, matches):
        child_errors.extend(child.validate_structure(dir_path))
    return child_errors
```

`File.validate_structure`: identical open, same `_validate_match_count` call, then stores `_resolved_paths`.

---

### 2. Guard `validate_content()` ordering — `schema.py`

**Problem:** `File.validate_content()` depends on `File._resolved_paths` being set by `validate_structure()`. If called first, it silently returns nothing.

**Design:**

- Change `_resolved_paths` default from `default_factory=list` to `default=None` (type: `list[Path] | None`)
- In `validate_structure`, always assign `_resolved_paths`: set to `[]` on error (file missing), set to resolved paths on success
- In `validate_content`, check `if self._resolved_paths is None: raise RuntimeError(...)` with a message directing users to `Schema.validate_all()`

This preserves the existing behavior when called via `Schema.validate_all()` (structure runs first, content sees non-None `_resolved_paths`).

---

### 3. Fix `NotImplemented` → `raise NotImplementedError` — `schema.py`

Covered by change 1: once `validate_structure` and `validate_content` are `@abstractmethod` on `Node`, the stubs are removed entirely. Python's ABC machinery enforces the contract at class definition time.

---

### 4. Fix typos in error messages — `errors.py`

- `MinMatchError.get_message`: `"To few"` → `"Too few"`
- `MaxMatchError.get_message`: `"To many"` → `"Too many"`

---

### 5. Add module docstrings — `errors.py`, `content.py`, `schema.py`

One-line module docstrings at the top of each file:
- `errors.py`: `"""Validation error types for structure and content failures."""`
- `content.py`: `"""Abstract base and built-in content validation rules."""`
- `schema.py`: `"""Schema node classes (Dir, File) and root Schema for filesystem validation."""`

---

### 6. Write README.md

Content:
- What mgnolia does (1-2 sentences)
- Installation (`pip install mgnolia` / `uv add mgnolia`)
- Quick-start example showing `Schema`, `Dir`, `File`, `validate_all`
- Short section on content rules (`FileNotEmptyRule`, `CSVSchemaRule`)
- Link to `examples/`

---

### 7. Replace pandera exploration script with real mgnolia example — `examples/`

Replace `examples/csv_schema_rule_demo.py` with `examples/validate_csv_directory.py` that demonstrates:
- Constructing a `Schema` with nested `Dir` and `File` nodes
- Attaching `CSVSchemaRule` and `FileNotEmptyRule` to a `File`
- Running `schema.validate_all()` against a real temp directory
- Printing errors when validation fails

---

## Files Changed

| File | Change |
|------|--------|
| `src/mgnolia/schema.py` | DRY fix, ordering guard, abc.ABC, abstractmethods, module docstring |
| `src/mgnolia/errors.py` | Typo fixes, module docstring |
| `src/mgnolia/content.py` | Module docstring |
| `README.md` | New content |
| `examples/validate_csv_directory.py` | New file (replaces demo) |
| `examples/csv_schema_rule_demo.py` | Delete |

---

## Verification

1. `pytest tests/` — all 51 existing tests pass unchanged
2. `pyright src/` — no new type errors (abstractmethod additions are type-safe)
3. `ruff check src/ examples/` — no lint issues
4. Manual: create a `File()` and call `validate_content()` directly → `RuntimeError` raised
5. Manual: run `examples/validate_csv_directory.py` and verify output shows expected errors/passes
