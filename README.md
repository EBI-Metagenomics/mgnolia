# mgnolia

Declarative filesystem structure and content validation for Python.

Define the expected layout of a directory using `Dir` and `File` nodes, optionally attach content validation rules, then call `validate_all()` to check a real directory against your schema. All errors are collected and returned as typed objects—nothing raises.

## Installation

**pip:**
```bash
pip install mgnolia
```

**uv:**
```bash
uv add mgnolia
```

## Quick Start

```python
from mgnolia import Dir, File, Schema

# Define expected structure
schema = Schema(
    children=[
        Dir(
            path="data",
            description="Data directory",
            children=[
                File(path="input.csv"),
                File(path="output.json"),
            ],
        ),
        File(path="config.yaml"),
    ]
)

# Validate a directory
ok = schema.validate_all("/path/to/project")

if not ok:
    for error in schema.errors:
        print(error)
else:
    print("All checks passed!")
```

## Content Rules

Attach validation rules to files to check their contents:

```python
from mgnolia import File
from mgnolia.content import FileNotEmptyRule, CSVSchemaRule
from pydantic import BaseModel

class UserRow(BaseModel):
    id: int
    name: str
    email: str

File(
    path="users.csv",
    content_rules=[
        FileNotEmptyRule(),
        CSVSchemaRule(schema=UserRow),
    ],
)
```

**Built-in rules:**
- `FileNotEmptyRule()` — fails if file is empty
- `CSVSchemaRule(schema=PydanticModel)` — validates CSV against a Pydantic model using pandera

Rules can also publish a value for a later node to use:

```python
from mgnolia import File, Schema, Value
from mgnolia.content import RowCountRule

user_count = Value[int]("users.row_count")
avatar_count = Value[int]("avatars.match_count")

schema = Schema(children=[
    File(path="users.parquet", content_rules=[
        RowCountRule(min=1, max=10_000, output=user_count),
    ]),
    File(
        path="user_avatars/*.png",
        min_matches=0,
        max_matches=user_count.ref(),
        output=avatar_count,
    ),
])
```

**Custom rules:**
Custom rules are subclasses of `ContentRule` (and optionally raising subclasses of `ContentValidationError`),
which implemennt a `validate` method on the node (`Dir` or more typically `File`).
They may also publish custom `Value`s for use in later rules.

As a realistic example, to validate that a directory contains TSV files named by a known format like an Accession,
e.g. `ERR123456.tsv`, `ERR987654.tsv` etc,
AND that each file contains the same accession it is named by (so like `grep -q 'ERR123456' ERR123456.tsv`)
we could define the following custom rules and values:

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

schema = Schema(children=[
    Dir(path="runs", children=[
        File(
            path="*.tsv",
            max_matches=None,
            content_rules=[
                FilenameRule(output=accession),
                ContainsTextRule(accession.ref()),
            ],
        ),
    ]),
])
```

This example works because content rules run in list order for each matched file. 
Thus, for `ERR123456.tsv`, `FilenameRule` publishes `ERR123456` and `ContainsTextRule`
consumes it while validating that same file.

References between separate nodes resolve in declaration order, so the
top-level subtree producing a value must appear before the subtree consuming it.
Compatible `Ref` values can be used for any parameter of the built-in content
rules, as well as `min_matches` and `max_matches`.

Observations can be published with `output=` even when their validation fails
(so that the validation report is as "complete" as possible):

- `File` and `Dir` output their actual number of matches.
- `FileNotEmptyRule` outputs the file size in bytes.
- `CSVSchemaRule` and `ParquetSchemaRule` output the actual Polars schema.
- `RowCountRule` outputs the actual row count.
- `SortedRule` outputs the column's `(min, max)` values.

## Error Types

When validation fails, `schema.errors` contains typed error objects:

- **Structure errors:** `FileMissingError`, `DirectoryMissingError`, `MinMatchError`, `MaxMatchError`
- **Content errors:** `FileEmptyError`, `ContentSchemaError`

All inherit from `ValidationError` and have `.path` and `.node` attributes. Use `str(error)` to get a formatted message.

## Pattern Matching

`Dir` and `File` paths support glob patterns to match multiple files or directories:

```python
File(path="*.log", min_matches=1)  # At least one .log file
Dir(path="test_*", max_matches=5)  # At most 5 test_* directories
```

## License

MIT
