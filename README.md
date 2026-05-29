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
