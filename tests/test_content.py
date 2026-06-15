from pathlib import Path

import polars as pl
import pytest

from mgnolia.content import ParquetSchemaRule, RowCountRule, SortedRule
from mgnolia.errors import NotSortedError, ParquetSchemaMismatchError, RowCountError
from mgnolia.schema import File


def _write_parquet(path: Path, df: pl.DataFrame) -> None:
    df.write_parquet(path)


def _node() -> File:
    return File(path="x.parquet")


# ---------- ParquetSchemaRule ----------


def test_parquet_schema_rule_returns_empty_when_schema_matches(tmp_path: Path) -> None:
    p = tmp_path / "ok.parquet"
    _write_parquet(p, pl.DataFrame({"id": [1, 2], "name": ["a", "b"]}))
    rule = ParquetSchemaRule({"id": pl.Int64, "name": pl.String})

    assert rule.validate(_node(), p) == []


def test_parquet_schema_rule_reports_missing_extra_and_wrong_dtype(
    tmp_path: Path,
) -> None:
    p = tmp_path / "bad.parquet"
    _write_parquet(p, pl.DataFrame({"id": [1, 2], "extra_col": ["a", "b"]}))
    rule = ParquetSchemaRule({"id": pl.Int32, "name": pl.String})

    errors = rule.validate(_node(), p)

    assert len(errors) == 1
    err = errors[0]
    assert isinstance(err, ParquetSchemaMismatchError)
    assert err.missing == {"name"}
    assert err.extra == {"extra_col"}
    assert err.wrong_dtype == {"id": (pl.Int32, pl.Int64)}


# ---------- RowCountRule ----------


def test_row_count_rule_exact_match(tmp_path: Path) -> None:
    p = tmp_path / "rows.parquet"
    _write_parquet(p, pl.DataFrame({"id": list(range(10))}))

    assert RowCountRule(exact=10).validate(_node(), p) == []


def test_row_count_rule_exact_mismatch_reports_actual(tmp_path: Path) -> None:
    p = tmp_path / "rows.parquet"
    _write_parquet(p, pl.DataFrame({"id": list(range(7))}))

    errors = RowCountRule(exact=10).validate(_node(), p)

    assert len(errors) == 1
    assert isinstance(errors[0], RowCountError)
    assert errors[0].actual == 7
    assert errors[0].exact == 10


def test_row_count_rule_min_max_inside_bounds(tmp_path: Path) -> None:
    p = tmp_path / "rows.parquet"
    _write_parquet(p, pl.DataFrame({"id": list(range(50))}))

    assert RowCountRule(min=10, max=100).validate(_node(), p) == []


def test_row_count_rule_min_violation(tmp_path: Path) -> None:
    p = tmp_path / "rows.parquet"
    _write_parquet(p, pl.DataFrame({"id": list(range(5))}))

    errors = RowCountRule(min=10).validate(_node(), p)

    assert len(errors) == 1
    assert errors[0].actual == 5


def test_row_count_rule_rejects_no_bounds() -> None:
    with pytest.raises(ValueError):
        RowCountRule()


def test_row_count_rule_rejects_exact_with_min() -> None:
    with pytest.raises(ValueError):
        RowCountRule(exact=10, min=5)


# ---------- SortedRule ----------


def test_sorted_rule_accepts_sorted_column(tmp_path: Path) -> None:
    p = tmp_path / "sorted.parquet"
    _write_parquet(p, pl.DataFrame({"id": [1, 2, 3]}))

    assert SortedRule("id").validate(_node(), p) == []


def test_sorted_rule_rejects_unsorted_column(tmp_path: Path) -> None:
    p = tmp_path / "unsorted.parquet"
    _write_parquet(p, pl.DataFrame({"id": [3, 1, 2]}))

    errors = SortedRule("id").validate(_node(), p)

    assert len(errors) == 1
    assert isinstance(errors[0], NotSortedError)
    assert errors[0].column == "id"


# ---------- Regression: shared-File-state bug under globbed parent ----------


def test_content_rules_run_against_every_matched_dir(tmp_path: Path) -> None:
    """
    Regression for the bug where a `Dir(path=glob)` reused its single
    declared `File` child across all matched directories, so content rules
    only ran against the last one.
    """
    from mgnolia.schema import Dir, Schema

    for i in range(3):
        chunk = tmp_path / f"chunk={i}"
        chunk.mkdir()
        # only chunk=1 gets the wrong schema; the other two are fine
        if i == 1:
            _write_parquet(chunk / "data.parquet", pl.DataFrame({"wrong": [1]}))
        else:
            _write_parquet(
                chunk / "data.parquet", pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
            )

    schema = Schema(
        children=[
            Dir(
                path="chunk=*",
                min_matches=3,
                max_matches=3,
                children=[
                    File(
                        path="*.parquet",
                        content_rules=[
                            ParquetSchemaRule({"id": pl.Int64, "name": pl.String})
                        ],
                    ),
                ],
            ),
        ]
    )

    schema.validate_all(tmp_path)
    assert len(schema.errors) == 1
    assert isinstance(schema.errors[0], ParquetSchemaMismatchError)
    assert schema.errors[0].path.parent.name == "chunk=1"
