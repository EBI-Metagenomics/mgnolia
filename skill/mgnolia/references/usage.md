# mgnolia usage guide for AI agents

This document is a practical guide for the `mgnolia` Python package. It explains how to turn a filesystem structure into a schema, how validation behaves, and how to diagnose failures.

Use this document for mgnolia's mechanics, then inspect that project's configuration, examples, tests, and fixture directories for domain-specific conventions.

## Contents

- [What mgnolia does](#what-mgnolia-does)
- [Translate requirements into nodes](#translate-requirements-into-nodes)
- [Basic schema](#basic-schema)
- [Repeated and optional paths](#repeated-and-optional-paths)
- [Per-directory repeated structures](#per-directory-repeated-structures)
- [Content validation](#content-validation)
- [Custom content rules](#custom-content-rules)
- [Publishing and consuming values](#publishing-and-consuming-values)
- [Validation lifecycle](#validation-lifecycle)
- [Diagnose failures](#diagnose-failures)
- [Agent workflow](#agent-workflow)
- [Common mistakes](#common-mistakes)

## What mgnolia does

mgnolia validates a directory against a declarative tree of `Schema`, `Dir`, and `File` nodes.

```text
Schema root
├── Dir path="reports"
│   └── File path="*.csv"
└── File path="config.yaml"
```

Each node describes a path relative to its parent and a permitted number of matches. `File` nodes may also run content rules (such as validating a CSV). Validation collects all discovered problems into `schema.errors` instead of stopping at the first failure.

Install or verify the dependency in the active environment before writing integration code:

```bash
uv add mgnolia
# or: pip install mgnolia
python -c "import mgnolia; from importlib.metadata import version; print(mgnolia.__file__); print(version('mgnolia'))"
```

Use public imports in application code:

```python
from mgnolia import Dir, File, Schema
from mgnolia.content import (
    CSVSchemaRule,
    FileNotEmptyRule,
    ParquetSchemaRule,
    RowCountRule,
    SortedRule,
)
```

## Translate requirements into nodes

Start with the filesystem contract in plain language, then map each statement to a node.

| Requirement | mgnolia expression |
| --- | --- |
| Exactly one known file | `File(path="config.yaml")` |
| Exactly one known directory | `Dir(path="reports")` |
| Optional file or directory | `min_matches=0` |
| At least one matching path | `min_matches=1, max_matches=None` |
| Between two and five matches | `min_matches=2, max_matches=5` |
| Any number of matching paths, including none | `min_matches=0, max_matches=None` |
| Match a pattern | `path="sample_*/result.parquet"` |
| Validate file contents | `File(..., content_rules=[...])` |

Node paths are relative to the node's parent. They may use `*`, `?`, and `[]` glob syntax. Node paths must not be absolute and must not contain `.` or `..` segments. The root passed to `Schema.validate_all()` may be absolute.

Defaults are important: `min_matches=1` and `max_matches=1`, so every node is required exactly once unless the bounds are changed.

## Basic schema

Suppose a project requires this layout:

```text
project/
├── config.yaml
├── data/
│   ├── input.csv
│   └── output.json
└── logs/
    └── run.log
```

Represent it as:

```python
from pathlib import Path

from mgnolia import Dir, File, Schema

schema = Schema(
    children=[
        File(path="config.yaml"),
        Dir(
            path="data",
            children=[
                File(path="input.csv"),
                File(path="output.json"),
            ],
        ),
        Dir(path="logs", children=[File(path="run.log")]),
    ]
)

root = Path("project")
if not schema.validate_all(root):
    for error in schema.errors:
        print(error)
```

`validate_all()` returns `True` only when there are no errors. It also clears errors from an earlier run, so the same schema instance can be reused after the directory changes.

## Repeated and optional paths

For a directory containing one or more CSV files, make the repetition explicit:

```python
schema = Schema(
    children=[
        Dir(
            path="reports",
            children=[
                File(path="*.csv", min_matches=1, max_matches=None),
            ],
        ),
    ]
)
```

For optional output artifacts:

```python
File(path="metrics.json", min_matches=0)
```

For exactly two or three shards:

```python
File(path="shard-*.parquet", min_matches=2, max_matches=3)
```

Use `max_matches=None` for an unbounded upper limit. `max_matches` cannot be less than `min_matches`.

A missing literal path produces `FileMissingError` or `DirectoryMissingError`. A glob with too few matches produces `MinMatchError`; too many produces `MaxMatchError`. The error path contains the literal or pattern used by the node.

## Per-directory repeated structures

Use a globbed `Dir` when every matching directory must contain the same children. Child paths are evaluated relative to each matched directory.

```text
run/
├── sample_A/
│   ├── reads.bam
│   └── results/
│       └── variants.vcf
└── sample_B/
    ├── reads.bam
    └── results/
        └── variants.vcf
```

```python
schema = Schema(
    children=[
        Dir(
            path="sample_*",
            min_matches=1,
            max_matches=None,
            children=[
                File(path="reads.bam"),
                Dir(path="results", children=[File(path="variants.vcf")]),
            ],
        ),
    ]
)
```

Errors are collected independently for each matched directory. If `sample_B/results/variants.vcf` is missing, the error points to that resolved location.

## Content validation

Attach one or more rules to a `File`. Each rule runs for every file matched by that node.

### CSV rows validated by Pydantic

```python
from pydantic import BaseModel

from mgnolia import Dir, File, Schema
from mgnolia.content import CSVSchemaRule, FileNotEmptyRule

class ReportRow(BaseModel):
    name: str
    age: int
    score: float

schema = Schema(
    children=[
        Dir(
            path="reports",
            children=[
                File(
                    path="*.csv",
                    min_matches=1,
                    max_matches=None,
                    content_rules=[
                        FileNotEmptyRule(),
                        CSVSchemaRule(schema=ReportRow),
                    ],
                )
            ],
        )
    ]
)
```

`CSVSchemaRule` validates CSV data through Pandera's Polars integration and returns `ContentSchemaError` instances. Add `FileNotEmptyRule()` separately if empty files should fail.

### Parquet schema, row count, and ordering

Use Polars dtypes for exact Parquet schema checks:

```python
import polars as pl

from mgnolia import File, Schema
from mgnolia.content import ParquetSchemaRule, RowCountRule, SortedRule

schema = Schema(
    children=[
        File(
            path="data.parquet",
            content_rules=[
                ParquetSchemaRule({
                    "id": pl.Int64,
                    "name": pl.String,
                }),
                RowCountRule(min=1, max=1_000_000),
                SortedRule("id", order="asc"),
            ],
        )
    ]
)
```

`ParquetSchemaRule` requires exact column names and dtypes. `RowCountRule` accepts either `exact=n` or `min`/`max` bounds; it requires at least one bound. `SortedRule` reports a missing column separately from an ordering failure.

## Custom content rules

Create a custom rule when the built-ins do not express a file-level invariant. Return a list of content errors, not a boolean and not an exception for an ordinary validation failure.

```python
from pathlib import Path

from mgnolia.content import ContentRule
from mgnolia.errors import ContentValidationError

class HeaderRule(ContentRule):
    def __init__(self, *, expected: str) -> None:
        super().__init__()
        self.expected = expected

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        with path.open(path, encoding="utf-8") as handle:
            actual = handle.readline().rstrip("\n")
        if actual == self.expected:
            return []
        return [ContentValidationError(node, path)]
```

Rules receive the owning `File` node and a resolved file path. They run once per matched file. Prefer deterministic, side-effect-free checks and return typed subclasses with useful fields/messages when the consuming project needs actionable diagnostics.

## Publishing and consuming values

A node or content rule can publish a measured value for a *later* node or rule to consume, using `Value` and `Ref` (both importable from top-level `mgnolia`):

```python
from mgnolia import File, Schema, Value
from mgnolia.content import RowCountRule
```

`Value[T]("name")` is a named slot. Pass it as `output=` to a `File`, `Dir`, or content rule constructor to have that node/rule populate it. Call `.ref()` on the `Value` to get a `Ref[T]`, which can be passed anywhere a later node/rule accepts a literal of matching type — `min_matches`, `max_matches`, or a rule constructor argument.

```python
user_count = Value[int]("users.row_count")
avatar_count = Value[int]("avatars.match_count")

schema = Schema(
    children=[
        # Producers must appear before consumers.
        File(
            path="users.parquet",
            content_rules=[
                RowCountRule(min=1, max=10_000, output=user_count),
            ],
        ),
        File(
            path="user_avatars/*.png",
            min_matches=0,
            max_matches=user_count.ref(),
            output=avatar_count,
        ),
    ]
)
```

Values can also flow between rules on the *same* `File`, since content rules run in list order for each matched file:

```python
import re
from pathlib import Path

from mgnolia import Dir, File, Ref, Schema, Value
from mgnolia.content import ContentRule
from mgnolia.errors import ContentValidationError
from mgnolia.schema import Node


class FilenameRule(ContentRule):
    def __init__(self, output: Value[str]) -> None:
        super().__init__(output)
        self.accession = output

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        self.accession.set(path.stem)
        if re.fullmatch(r"ERR\d{6}\.tsv", path.name):
            return []
        return [ContentValidationError(node, path)]


class ContainsTextRule(ContentRule):
    def __init__(self, expected: Ref[str]) -> None:
        super().__init__()
        self.expected = expected

    def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
        expected = self.expected.resolve()
        if expected in path.read_text(encoding="utf-8"):
            return []
        return [ContentValidationError(node, path)]


accession = Value[str]("current_accession")

schema = Schema(
    children=[
        Dir(
            path="runs",
            children=[
                File(
                    path="*.tsv",
                    max_matches=None,
                    content_rules=[
                        FilenameRule(output=accession),
                        ContainsTextRule(accession.ref()),
                    ],
                ),
            ],
        ),
    ]
)
```

For `ERR123456.tsv`, `FilenameRule` publishes `ERR123456` and `ContainsTextRule` consumes it while validating that same file. A custom rule that wants to publish a value should accept `output: Value[T] | None = None`, pass it to `super().__init__(output)`, and call `self.output.set(...)` inside `validate()` (ideally before any early return, so the value is set even on failure).

References resolve in declaration order: the top-level subtree that produces a value must be declared before the subtree that consumes it. Calling `.resolve()` on a `Ref` whose `Value` has not been published yet raises `RuntimeError`.

The following built-ins support `output=` and publish their measured result even when the check fails:

- `File` and `Dir` publish their actual number of matches.
- `FileNotEmptyRule` publishes the file size in bytes.
- `CSVSchemaRule` and `ParquetSchemaRule` publish the actual Polars schema.
- `RowCountRule` publishes the actual row count.
- `SortedRule` publishes the column's `(min, max)` values.

A `Ref` can be used for `min_matches`, `max_matches`, or any compatible parameter of the built-in content rules. `schema.validate_all()` clears every `Value` at the start of each run, so a reused `Schema` never reads a stale value from a previous run.

## Validation lifecycle

The normal lifecycle is always:

```text
Schema.validate_all(root)
        │
        ├── validate structure for each child
        │       └── resolve matches and enforce min/max
        │
        └── validate content for successfully resolved files
```

Use `validate_all()` in the application code. Direct calls to `validate_structure()` and `validate_content()` are mainly useful in focused tests.
Calling `validate_content()` before structure validation raises `RuntimeError`.

If a file node fails its match-count check, its content rules are skipped. This prevents a missing or ambiguous path from causing secondary file-reading errors.

## Diagnose failures

Inspect all errors rather than only the first one:

```python
if not schema.validate_all(root):
    for error in schema.errors:
        print(error)
```

Use this order when debugging:

1. Confirm the root passed to `validate_all()` is the intended directory.
2. Check literal paths and parent directories.
3. Check glob spelling and match bounds.
4. Check whether the content rule matches the file format.
5. Inspect rule-specific fields such as `missing`, `extra`, `wrong_dtype`, `actual`, `exact`, `min`, `max`, `column`, and `order`.

Error families:

- Structure: `FileMissingError`, `DirectoryMissingError`, `MinMatchError`, `MaxMatchError`.
- Content: `FileEmptyError`, `ContentSchemaError`, `ParquetSchemaMismatchError`, `RowCountError`, `NotSortedError`, `MissingColumnError`.

All errors expose `.path` and `.node`. `str(error)` produces a concise human-readable message.

## Agent workflow

When asked to add or change validation in an unfamiliar project:

1. Inspect the installed mgnolia version and the project's dependency file.
2. Inspect existing schema declarations, examples, fixtures, validation tests and project documentation (README.md, docs/usage.md and docs/outputs.md)
3. Write down the intended layout and cardinality before editing code.
4. Map each requirement to a node or content rule; do not use a custom rule if a built-in rule suffices.
5. Add or update a fixture that demonstrates both a passing case and the expected failure case.
6. Report all errors in a stable, useful format such as CSV or JSON.
7. Run the project's normal tests and static checks.

Keep domain policy in the consuming project. mgnolia should express the contract, not invent names, file ownership, or business rules that the project has not established.

## Common mistakes

- Forgetting that a node defaults to exactly one match.
- Using a child path relative to the project root instead of relative to its parent `Dir`.
- Setting `max_matches=1` when the requirement is “one or more”; use `max_matches=None`.
- Expecting a content rule to run when the file is missing or has an invalid match count.
- Treating `validate_all()` as exception-based; ordinary failures are returned as `False` and stored in `schema.errors`.
- Using `CSVSchemaRule` for Parquet or `ParquetSchemaRule` for CSV.
- Assuming `File` and `Dir` enforce filesystem object type; current matching is based on paths returned by `Path.glob`, so verify this behavior before relying on it.
- Referencing a `Value` via `Ref.resolve()` before its producing node/rule is declared; resolution follows declaration order and an unset `Value` raises `RuntimeError`.
- Forgetting `output=` on the producing node/rule, so the `Value` is never populated for a later `Ref` to consume.
