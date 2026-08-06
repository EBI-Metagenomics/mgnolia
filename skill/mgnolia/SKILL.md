---
name: mgnolia
description: Use when designing, debugging, extending, or testing Python code that uses the mgnolia library for declarative filesystem layout and content validation, including Schema, Dir, File, glob match cardinality, custom ContentRule implementations, CSV/Pydantic validation, Parquet schema checks, row counts, sorted columns, and typed validation errors.
---

# mgnolia

Use this skill as the fast operating guide for the installed `mgnolia` package. Assume the consuming project has installed it with `pip` or `uv`; inspect the active environment and public package imports rather than expecting the library's source checkout to be present. If this guide and the installed package differ, the installed package wins.

For concrete recipes and agent-oriented usage patterns, read [references/usage.md](references/usage.md) in the library repository when it is available. In a consuming project, use that document as the mgnolia cookbook and the consuming project's own tests and examples as the domain-specific authority.

## Core model

- `Schema(children=[...])` is the root. `Schema(path=...)` supplies a default root; `validate_all(root_path)` uses the argument when non-`None`, otherwise the instance path, then resolves it.
- `Dir(path=..., children=[...])` declares nested directory nodes.
- `File(path=..., content_rules=[...])` declares files and optional content checks.
- Node paths are relative and reject absolute paths plus `.`/`..` path segments. The root path may be absolute and may contain those segments.
- Node models use Pydantic with `extra="forbid"`; unknown configuration keys are errors.
- Public imports are `from mgnolia import Schema, Dir, File`. Content rules are in `mgnolia.content`; error classes are in `mgnolia.errors`.
- `Value` and `Ref` are also public imports (`from mgnolia import Value, Ref`). `Node.output`, `ContentRule.output`, and `min_matches`/`max_matches` all accept a `Ref` in place of a literal, letting one node/rule's measured result drive another node/rule declared later. See "Inter-node/inter-rule values" below.

Confirm the dependency before making changes in a consuming project:

```bash
python -c "import mgnolia; from importlib.metadata import version; print(mgnolia.__file__); print(version('mgnolia'))"
```

Use `uv add mgnolia` or `pip install mgnolia` when it is missing, but always check if there is a virtual enviroment. When behavior is version-sensitive, record the installed version and inspect the installed modules with `help()` or `inspect`.

## Standard workflow

1. Build the schema from the outside in, using paths relative to the node's parent.
2. Set `min_matches` and `max_matches` deliberately. Defaults are `1` and `1`; use `max_matches=None` for an unbounded upper limit.
3. Call `ok = schema.validate_all(root_path)`.
4. On failure, inspect every item in `schema.errors`; validation aggregates errors and returns `False`, it does not raise for ordinary validation failures.
5. Use `type(error).__name__`, `error.path`, `error.node`, `error.error_type`, and `str(error)` for reporting. A later `validate_all()` clears prior errors.

```python
from mgnolia import Dir, File, Schema
from mgnolia.content import FileNotEmptyRule

schema = Schema(children=[
    Dir(path="reports", children=[
        File(path="*.csv", min_matches=1, max_matches=None,
             content_rules=[FileNotEmptyRule()]),
    ]),
])

if not schema.validate_all(project_root):
    for error in schema.errors:
        print(f"[{type(error).__name__}] {error}")
```

## Matching semantics and important gotchas

- Paths support `pathlib` glob syntax (`*`, `?`, `[]`). A literal path still uses the same match-count machinery.
- `min_matches` is non-negative; `max_matches` is positive or `None`, and cannot be below `min_matches`.
- `min_matches=0` makes a node optional. A glob with too few matches reports `MinMatchError`; a literal with no match reports `FileMissingError` or `DirectoryMissingError`.
- `max_matches` violations report `MaxMatchError` and include the pattern path.
- Matching currently counts paths returned by `Path.glob` without checking whether a `File` match is actually a regular file or a `Dir` match is actually a directory. Preserve this behavior unless explicitly fixing it.
- Validation has two phases: structure first, then content. Content rules are skipped when that `File` did not resolve successfully. Direct calls to `validate_content()` before `validate_structure()` raise `RuntimeError`; prefer `validate_all()`.
- A globbed `Dir` validates each child independently for every matched directory. Do not reuse mutable/private resolution state in custom node logic without accounting for this.
- `File` content rules run once per rule per resolved file, and may return multiple `ContentValidationError` instances.

## Built-in content rules

```python
from mgnolia.content import (
    CSVSchemaRule, FileNotEmptyRule, ParquetSchemaRule,
    RowCountRule, SortedRule,
)
```

- `FileNotEmptyRule()` checks `path.stat().st_size` and returns `FileEmptyError` for zero-byte files.
- `CSVSchemaRule(schema=RowModel)` uses a Pydantic `BaseModel` through pandera's Polars engine. It lazily scans CSV data and returns `ContentSchemaError` objects for schema failures.
- `ParquetSchemaRule({"id": pl.Int64, "name": pl.String})` compares exact column names and exact Polars dtypes. Its one error exposes `missing`, `extra`, and `wrong_dtype`.
- `RowCountRule(exact=n)` or `RowCountRule(min=n, max=m)` checks Parquet row counts. It requires at least one bound; `exact` cannot be combined with `min`/`max`; `min` cannot exceed `max`.
- `SortedRule("column", order="asc"|"desc")` checks a Parquet column with a Polars scan. A missing column returns `MissingColumnError`; bad order returns `NotSortedError`.

Parquet rules are intended for Parquet files; CSV validation is the Pydantic-backed CSV rule. Add `FileNotEmptyRule()` separately when emptiness must be rejected.

## Custom rules and extensions

Subclass `ContentRule` and implement:

```python
from pathlib import Path
from mgnolia.content import ContentRule
from mgnolia.errors import ContentValidationError

class MyRule(ContentRule):
    def validate(self, node, path: Path) -> list[ContentValidationError]:
        return []
```

Return an empty list for success and typed `ContentValidationError` instances for failures. Keep rules side-effect free where possible; `validate()` receives the resolved absolute file path and owning `File` node. Accept an optional `output: Value[T] | None = None` and pass it to `super().__init__(output)` to let the rule publish a value (see below); call `self.output.set(...)` inside `validate()`, ideally before any early return, so the value is published even on failure.

## Inter-node/inter-rule values (`Value`/`Ref`)

- `Value[T]("name")` (from `mgnolia`) is a named slot that a node or content rule populates by passing `output=` at construction time. `.ref()` on a `Value` produces a `Ref[T]`, which can be passed anywhere a later node/rule accepts a literal of that type (`min_matches`, `max_matches`, or a rule constructor argument such as `RowCountRule(max=...)` or `SortedRule(column=...)`).
- `resolve(x)` (from `mgnolia.values`, used internally) unwraps a `Ref` or passes a literal through unchanged; consuming code usually just calls `ref.resolve()` directly or passes the `Ref` straight into another node/rule parameter.
- Resolution follows declaration order: the producing node/rule must be declared before the consuming node/rule. Resolving a `Ref` whose `Value` has not been set yet raises `RuntimeError`.
- Built-in producers (all support `output=`): `File`/`Dir` publish their match count; `FileNotEmptyRule` publishes file size in bytes; `CSVSchemaRule`/`ParquetSchemaRule` publish the actual Polars schema; `RowCountRule` publishes the actual row count; `SortedRule` publishes the column's `(min, max)`. Values are set even when the corresponding check fails, so error reporting stays complete.
- `schema.validate_all()` clears every `Value` at the start of the run (via `Schema._reset_outputs`), so a reused `Schema` instance never reads a stale value from a prior run.

```python
from mgnolia import File, Schema, Value
from mgnolia.content import RowCountRule

user_count = Value[int]("users.row_count")

schema = Schema(children=[
    File(path="users.parquet", content_rules=[
        RowCountRule(min=1, max=10_000, output=user_count),
    ]),
    File(path="user_avatars/*.png", min_matches=0, max_matches=user_count.ref()),
])
```

## Error map

Structure errors: `FileMissingError`, `DirectoryMissingError`, `MinMatchError`, `MaxMatchError`.

Content errors: `FileEmptyError`, `ContentSchemaError`, `ParquetSchemaMismatchError`, `RowCountError`, `NotSortedError`, `MissingColumnError` (plus the base `ContentValidationError`). All errors expose `.path` and `.node`; content errors have `error_type == "content"`, structure errors have `error_type == "structure"`.

## Efficient work in a consuming project

- Start with the consuming project's dependency declaration and the installed package version.
- Search the consuming project's own tests, examples and documentation for its intended schema patterns. For Nextflow pipelines look for docs/outputs.md or similar where the pipeline outputs are described.
- Run that project's normal test, lint, and type-check commands after changing its integration code.
- Preserve the installed package's supported Python and dependency constraints; do not copy internal implementation details into application code.
