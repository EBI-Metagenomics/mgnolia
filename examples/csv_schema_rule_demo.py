"""Demonstrates what information is available from pandera SchemaError/SchemaErrors."""

import tempfile
from pathlib import Path

import pandera.polars as pa
import polars as pl
from pandera.engines.polars_engine import PydanticModel
from pandera.errors import SchemaError, SchemaErrors
from pydantic import BaseModel


class Row(BaseModel):
    id: int
    name: str
    score: float


schema = pa.DataFrameSchema(dtype=PydanticModel(Row), coerce=True)

invalid_csv = "id,name,score\nnot_an_int,Alice,9.5\n2,Bob,not_a_float\n"

with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
    f.write(invalid_csv)
    path = Path(f.name)

lf = pl.scan_csv(path)

# --- Without lazy=True: raises SchemaError on first failure only ---
print("=== SchemaError (no lazy) ===")
try:
    schema.validate(lf).collect()
except SchemaError as e:
    print(e.schema)
    print(e.failure_cases)
    print(e.check)
    print(e.check_index)
    print(e.check_output)

    print(e.parser_output)
    print(e.reason_code)
    print(e.column_name)
    print("reason_code  :", e.reason_code)
    print("message      :", e.args[0])
    print("failure_cases:", e.failure_cases)

# --- With lazy=True: collects all failures into SchemaErrors ---
print("\n=== SchemaErrors (lazy=True) ===")
try:
    schema.validate(lf, lazy=True).collect()
except SchemaErrors as e:
    print("error_counts :", e.error_counts)
    for err in e.schema_errors:
        print(err.column_name)
        print(err.check_index)
        print(err.parser_index)
        print(err.data)
        print(f"  [{err.reason_code.name}] {err.args[0]}")
        print(f"    failure_cases: {err.failure_cases}")
except SchemaError as e:
    # PydanticModel may still raise SchemaError even with lazy=True
    print(e.column_name)
    print(e.check_index)
    print(e.parser_index)
    print(e.data)
    print("reason_code  :", e.reason_code)
    print("message      :", e.args[0])
    print("failure_cases:", e.failure_cases)

path.unlink()
