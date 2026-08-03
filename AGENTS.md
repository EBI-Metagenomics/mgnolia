# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.13+ package using a `src` layout:

- `src/mgnolia/` contains the public package, schema models, validation rules, and typed errors.
- `tests/` contains pytest tests, organized primarily by module (`test_schema.py` and `test_content.py`).
- `examples/` contains runnable usage examples, such as `validate_csv_directory.py`.
- `skill/mgnolia/` contains the agent-facing skill and its usage reference.
- `README.md`, `LICENSE`, `Taskfile.yml`, `pyproject.toml`, and `uv.lock` provide project documentation, development tasks, metadata, and locked dependencies.

Keep new library code under `src/mgnolia`; do not import from implementation files through filesystem paths.

## Build, Test, and Development Commands

Use the Taskfile for common development commands. Install the locked environment with:

```bash
task setup
```

Run the full check suite, or individual checks, with:

```bash
task
task test
task lint
task format-check
task typecheck
```

Tasks use `uv` for dependency installation and command execution. The equivalent direct commands are:

```bash
uv sync --locked --all-extras --dev
uv run --frozen pytest -v
uv run ruff check .
uv run pyright
```

Run examples directly with `uv run python examples/validate_csv_directory.py` when changing user-facing behavior.

## Coding Style & Naming Conventions

Use four spaces, type annotations, and clear, descriptive names. Follow standard Python naming: `snake_case` for functions, methods, and variables; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Keep public APIs and validation errors explicit and typed. Format and lint with Ruff; target Python 3.13.

## Testing Guidelines

Use pytest and name test files `test_*.py` and test functions `test_*`. Prefer focused tests with `tmp_path` for filesystem behavior and parametrization for related input cases. Add regression coverage for bug fixes and run the complete suite before opening a PR.
