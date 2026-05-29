"""Example: validate a directory of CSV report files using mgnolia."""

import shutil
import tempfile
from pathlib import Path

from pydantic import BaseModel

from mgnolia import Dir, File, Schema
from mgnolia.content import CSVSchemaRule, FileNotEmptyRule


# Pydantic model describing the expected shape of each CSV row
class ReportRow(BaseModel):
    name: str
    age: int
    score: float


# Schema: a reports/ dir with at least one *.csv, each non-empty and row-valid
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


def run_scenario(label: str, tmp_dir: Path) -> None:
    print(f"\n=== {label} ===")
    passed = schema.validate_all(tmp_dir)
    if passed:
        print("Result: PASSED — no validation errors")
    else:
        print(f"Result: FAILED — {len(schema.errors)} error(s)")
        for err in schema.errors:
            print(f"  [{type(err).__name__}] {err}")


tmp = Path(tempfile.mkdtemp())
reports_dir = tmp / "reports"
reports_dir.mkdir()

try:
    # --- Scenario 1: only a valid CSV present ---
    valid_csv = reports_dir / "summary.csv"
    valid_csv.write_text("name,age,score\nAlice,30,9.5\nBob,25,8.0\n")

    run_scenario("Scenario 1: valid directory (summary.csv only)", tmp)

    # --- Scenario 2: add an invalid CSV with wrong column types ---
    invalid_csv = reports_dir / "invalid.csv"
    # 'age' is not an int, 'score' is not a float
    invalid_csv.write_text("name,age,score\nCharlie,not_an_int,nine\n")

    run_scenario("Scenario 2: directory with invalid.csv added", tmp)

finally:
    shutil.rmtree(tmp)
    print("\nTemp directory cleaned up.")
