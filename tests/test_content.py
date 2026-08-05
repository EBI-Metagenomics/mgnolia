from pathlib import Path
from typing import Literal

import polars as pl
import pytest
from pydantic import BaseModel

from mgnolia.content import (
    CSVSchemaRule,
    FileNotEmptyRule,
    ParquetSchemaRule,
    RowCountRule,
    SortedRule,
)
from mgnolia.errors import (
    MaxMatchError,
    NotSortedError,
    ParquetSchemaMismatchError,
    RowCountError,
)
from mgnolia.schema import File, Schema
from mgnolia.values import Value


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


def test_row_count_rule_publishes_actual_count(tmp_path: Path) -> None:
    p = tmp_path / "rows.parquet"
    _write_parquet(p, pl.DataFrame({"id": list(range(7))}))
    rows = Value[int]("rows")

    RowCountRule(exact=10, output=rows).validate(_node(), p)

    assert rows.ref().resolve() == 7


def test_builtin_rule_parameters_accept_refs(tmp_path: Path) -> None:
    parquet = tmp_path / "rows.parquet"
    _write_parquet(parquet, pl.DataFrame({"id": [1, 2]}))
    expected_schema = Value[dict[str, pl.DataType]]("schema")
    exact = Value[int]("exact")
    minimum = Value[int]("minimum")
    maximum = Value[int]("maximum")
    column = Value[str]("column")
    order = Value[Literal["asc", "desc"]]("order")
    actual_schema = Value[dict[str, pl.DataType]]("actual_schema")
    extent = Value[tuple[object, object]]("extent")
    file_size = Value[int]("file_size")
    expected_schema.set({"id": pl.Int64})
    exact.set(2)
    minimum.set(1)
    maximum.set(3)
    column.set("id")
    order.set("asc")

    assert (
        ParquetSchemaRule(expected_schema.ref(), output=actual_schema).validate(
            _node(), parquet
        )
        == []
    )
    assert RowCountRule(exact=exact.ref()).validate(_node(), parquet) == []
    assert (
        RowCountRule(min=minimum.ref(), max=maximum.ref()).validate(_node(), parquet)
        == []
    )
    assert (
        SortedRule(column.ref(), order=order.ref(), output=extent).validate(
            _node(), parquet
        )
        == []
    )
    assert FileNotEmptyRule(output=file_size).validate(_node(), parquet) == []
    assert actual_schema.ref().resolve() == {"id": pl.Int64}
    assert extent.ref().resolve() == (1, 2)
    assert file_size.ref().resolve() > 0

    class Row(BaseModel):
        id: int

    csv = tmp_path / "rows.csv"
    csv.write_text("id\n1\n", encoding="utf-8")
    csv_schema = Value[type[BaseModel]]("csv_schema")
    actual_csv_schema = Value[dict[str, pl.DataType]]("actual_csv_schema")
    csv_schema.set(Row)
    assert (
        CSVSchemaRule(csv_schema.ref(), output=actual_csv_schema).validate(
            _node(), csv
        )
        == []
    )
    assert actual_csv_schema.ref().resolve() == {"id": pl.Int64}


def test_row_count_can_limit_later_file_matches(tmp_path: Path) -> None:
    _write_parquet(tmp_path / "users.parquet", pl.DataFrame({"id": [1, 2]}))
    avatars = tmp_path / "user_avatars"
    avatars.mkdir()
    for name in ("1.png", "2.png", "3.png"):
        (avatars / name).touch()
    user_count = Value[int]("users.row_count")
    avatar_count = Value[int]("avatars.match_count")
    schema = Schema(
        children=[
            File(
                path="users.parquet",
                content_rules=[RowCountRule(min=1, max=10_000, output=user_count)],
            ),
            File(
                path="user_avatars/*.png",
                min_matches=0,
                max_matches=user_count.ref(),
                output=avatar_count,
            ),
        ]
    )

    assert schema.validate_all(tmp_path) is False
    assert len(schema.errors) == 1
    assert isinstance(schema.errors[0], MaxMatchError)
    assert avatar_count.ref().resolve() == 3


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


def test_sorted_rule_reports_missing_column(tmp_path: Path) -> None:
    from mgnolia.errors import MissingColumnError

    p = tmp_path / "data.parquet"
    _write_parquet(p, pl.DataFrame({"id": [1, 2, 3]}))

    errors = SortedRule("does_not_exist").validate(_node(), p)

    assert len(errors) == 1
    assert isinstance(errors[0], MissingColumnError)
    assert errors[0].column == "does_not_exist"


def test_sorted_rule_accepts_descending_column(tmp_path: Path) -> None:
    p = tmp_path / "desc.parquet"
    _write_parquet(p, pl.DataFrame({"id": [3, 2, 1]}))

    assert SortedRule("id", order="desc").validate(_node(), p) == []


def test_sorted_rule_rejects_ascending_column_when_desc_expected(
    tmp_path: Path,
) -> None:
    p = tmp_path / "asc.parquet"
    _write_parquet(p, pl.DataFrame({"id": [1, 2, 3]}))

    errors = SortedRule("id", order="desc").validate(_node(), p)

    assert len(errors) == 1
    assert isinstance(errors[0], NotSortedError)
    assert errors[0].order == "desc"


def test_sorted_rule_accepts_sorted_string_column(tmp_path: Path) -> None:
    p = tmp_path / "sorted_str.parquet"
    _write_parquet(p, pl.DataFrame({"v": ["MGYP000000000001", "MGYP000000000002", "MGYP000000000003"]}))

    assert SortedRule("v").validate(_node(), p) == []


def test_sorted_rule_rejects_unsorted_string_column(tmp_path: Path) -> None:
    p = tmp_path / "unsorted_str.parquet"
    _write_parquet(p, pl.DataFrame({"v": ["MGYP000000000002", "MGYP000000000001", "MGYP000000000003"]}))

    errors = SortedRule("v").validate(_node(), p)

    assert len(errors) == 1
    assert isinstance(errors[0], NotSortedError)
    assert errors[0].column == "v"


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
