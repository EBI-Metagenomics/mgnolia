from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError as PydanticValidationError

from mgnolia.content import ContentRule, CSVSchemaRule, FileNotEmptyRule
from mgnolia.errors import (
    ContentSchemaError,
    ContentValidationError,
    DirectoryMissingError,
    FileEmptyError,
    FileMissingError,
    MaxMatchError,
    MinMatchError,
)
from mgnolia.schema import Dir, File, Node, Schema


def test_node_uses_expected_defaults() -> None:
    # Node is abstract; use Dir as a concrete representative
    node = Dir(path="results")

    assert node.path == Path("results")
    assert node.min_matches == 1
    assert node.max_matches == 1
    assert node.description is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("results", False),
        ("results/*.txt", True),
        ("results/sample?.txt", True),
        ("results/[ab].txt", True),
    ],
)
def test_node_path_is_glob(path: Path, expected: bool) -> None:
    assert Dir(path=path).path_is_glob is expected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"path": "/absolute"}, "path must be relative"),
        ({"path": "parent/../child"}, "path must not contain"),
        ({"path": "results", "extra": "value"}, "Extra inputs are not permitted"),
        ({"path": "results", "min_matches": -1}, "greater than or equal to 0"),
        ({"path": "results", "max_matches": 0}, "greater than 0"),
        (
            {"path": "results", "min_matches": 2, "max_matches": 1},
            "max_matches must be greater than or equal to min_matches",
        ),
    ],
)
def test_node_rejects_invalid_model_values(
    kwargs: dict[str, Any], message: str
) -> None:
    with pytest.raises(PydanticValidationError, match=message):
        Dir(**kwargs)


def test_node_allows_unbounded_max_matches() -> None:
    assert Dir(path="results", max_matches=None).max_matches is None


def test_node_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        Node(path="results")  # type: ignore[abstract]


def test_node_is_abstract() -> None:
    import abc

    assert issubclass(Node, abc.ABC)
    assert hasattr(Node, "__abstractmethods__")


def test_dir_validate_content_raises_if_validate_structure_not_called() -> None:
    dir_node = Dir(path="results")
    with pytest.raises(RuntimeError, match="validate_structure\\(\\) must be called"):
        dir_node.validate_content()


def test_dir_uses_expected_defaults() -> None:
    directory = Dir(path="results")

    assert directory.children == []


def test_dir_reports_missing_literal_directory(tmp_path: Path) -> None:
    directory = Dir(path="results")

    errors = directory.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], DirectoryMissingError)
    assert errors[0].node is directory
    assert errors[0].path == tmp_path / "results"


def test_dir_reports_min_match_error_for_missing_glob(tmp_path: Path) -> None:
    directory = Dir(path="sample_*", min_matches=2, max_matches=None)
    (tmp_path / "sample_001").mkdir()

    errors = directory.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], MinMatchError)
    assert errors[0].node is directory
    assert errors[0].path == tmp_path / "sample_*"


def test_dir_reports_max_match_error(tmp_path: Path) -> None:
    directory = Dir(path="sample_*", max_matches=1)
    (tmp_path / "sample_001").mkdir()
    (tmp_path / "sample_002").mkdir()

    errors = directory.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], MaxMatchError)
    assert errors[0].node is directory
    assert errors[0].path == tmp_path / "sample_*"


def test_dir_returns_no_errors_when_match_count_is_valid(tmp_path: Path) -> None:
    directory = Dir(path="results")
    (tmp_path / "results").mkdir()

    assert directory.validate_structure(tmp_path) == []


def test_dir_allows_unbounded_max_matches(tmp_path: Path) -> None:
    directory = Dir(path="sample_*", min_matches=2, max_matches=None)
    (tmp_path / "sample_001").mkdir()
    (tmp_path / "sample_002").mkdir()
    (tmp_path / "sample_003").mkdir()

    assert directory.validate_structure(tmp_path) == []


def test_dir_validates_children_inside_each_matched_directory(tmp_path: Path) -> None:
    directory = Dir(
        path="sample_*",
        min_matches=2,
        max_matches=None,
        children=[File(path="results.vcf.gz")],
    )
    (tmp_path / "sample_001").mkdir()
    (tmp_path / "sample_001" / "results.vcf.gz").write_text("vcf", encoding="utf-8")
    (tmp_path / "sample_002").mkdir()

    errors = directory.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], FileMissingError)
    assert errors[0].path == tmp_path / "sample_002" / "results.vcf.gz"


def test_dir_aggregates_child_errors_across_matched_directories(tmp_path: Path) -> None:
    directory = Dir(
        path="sample_*",
        min_matches=2,
        max_matches=None,
        children=[File(path="results.vcf.gz"), Dir(path="logs")],
    )
    (tmp_path / "sample_001").mkdir()
    (tmp_path / "sample_002").mkdir()

    errors = directory.validate_structure(tmp_path)

    assert [type(error) for error in errors] == [
        FileMissingError,
        FileMissingError,
        DirectoryMissingError,
        DirectoryMissingError,
    ]
    assert [error.path for error in errors] == [
        tmp_path / "sample_001" / "results.vcf.gz",
        tmp_path / "sample_002" / "results.vcf.gz",
        tmp_path / "sample_001" / "logs",
        tmp_path / "sample_002" / "logs",
    ]


def test_dir_currently_counts_file_matches(tmp_path: Path) -> None:
    directory = Dir(path="results")
    (tmp_path / "results").write_text("not a directory", encoding="utf-8")

    assert directory.validate_structure(tmp_path) == []


def test_file_uses_expected_defaults() -> None:
    file_node = File(path="results.txt")

    assert file_node.content_rules == []


def test_file_accepts_content_rules() -> None:
    rule = FileNotEmptyRule()

    file_node = File(path="results.txt", content_rules=[rule])

    assert file_node.content_rules == [rule]


def test_file_reports_missing_literal_file(tmp_path: Path) -> None:
    file_node = File(path="results.txt")

    errors = file_node.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], FileMissingError)
    assert errors[0].node is file_node
    assert errors[0].path == tmp_path / "results.txt"


def test_file_reports_min_match_error_for_missing_glob(tmp_path: Path) -> None:
    file_node = File(path="*.txt", min_matches=2, max_matches=None)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    errors = file_node.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], MinMatchError)
    assert errors[0].node is file_node
    assert errors[0].path == tmp_path / "*.txt"


def test_file_reports_max_match_error(tmp_path: Path) -> None:
    file_node = File(path="*.txt", max_matches=1)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    errors = file_node.validate_structure(tmp_path)

    assert len(errors) == 1
    assert isinstance(errors[0], MaxMatchError)
    assert errors[0].node is file_node
    assert errors[0].path == tmp_path / "*.txt"


def test_file_returns_no_errors_when_match_count_is_valid(tmp_path: Path) -> None:
    file_node = File(path="results.txt")
    (tmp_path / "results.txt").write_text("results", encoding="utf-8")

    assert file_node.validate_structure(tmp_path) == []


def test_file_allows_unbounded_max_matches(tmp_path: Path) -> None:
    file_node = File(path="*.txt", min_matches=2, max_matches=None)
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "c.txt").write_text("c", encoding="utf-8")

    assert file_node.validate_structure(tmp_path) == []


def test_file_currently_counts_directory_matches(tmp_path: Path) -> None:
    file_node = File(path="results.txt")
    (tmp_path / "results.txt").mkdir()

    assert file_node.validate_structure(tmp_path) == []


def test_file_validate_content_calls_rule_for_each_resolved_path(
    tmp_path: Path,
) -> None:
    checked: list[tuple[object, Path]] = []

    class TrackingRule(ContentRule):
        def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
            checked.append((node, path))
            return []

    file_node = File(
        path="*.txt", min_matches=2, max_matches=None, content_rules=[TrackingRule()]
    )
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    file_node.validate_structure(tmp_path)
    file_node.validate_content()

    assert all(n is file_node for n, _ in checked)
    assert {p for _, p in checked} == {
        (tmp_path / "a.txt").resolve(),
        (tmp_path / "b.txt").resolve(),
    }


def test_file_validate_content_collects_errors_from_rules(tmp_path: Path) -> None:
    (tmp_path / "results.txt").write_text("content", encoding="utf-8")

    class FailingRule(ContentRule):
        def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
            return [ContentValidationError(node, path)]

    file_node = File(path="results.txt", content_rules=[FailingRule()])
    file_node.validate_structure(tmp_path)
    errors = file_node.validate_content()

    assert len(errors) == 1
    assert isinstance(errors[0], ContentValidationError)
    assert errors[0].node is file_node
    assert errors[0].path == (tmp_path / "results.txt").resolve()


def test_file_validate_content_ignores_none_from_rules(tmp_path: Path) -> None:
    (tmp_path / "results.txt").write_text("content", encoding="utf-8")

    class PassingRule(ContentRule):
        def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
            return []

    file_node = File(path="results.txt", content_rules=[PassingRule()])
    file_node.validate_structure(tmp_path)

    assert file_node.validate_content() == []


def test_file_validate_content_skips_rules_when_structure_validation_failed(
    tmp_path: Path,
) -> None:
    calls: list[Path] = []

    class TrackingRule(ContentRule):
        def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
            calls.append(path)
            return []

    file_node = File(path="missing.txt", content_rules=[TrackingRule()])
    file_node.validate_structure(tmp_path)
    file_node.validate_content()

    assert calls == []


def test_schema_is_a_root_model_with_recursive_children(tmp_path: Path) -> None:
    schema = Schema(
        path="run", children=[Dir(path="alignments", children=[File(path="*.bam")])]
    )
    (tmp_path / "alignments").mkdir()
    (tmp_path / "alignments" / "sample.bam").write_text("bam", encoding="utf-8")

    assert schema.validate_all(tmp_path) is True
    assert schema.errors == []


def test_schema_validates_complex_nested_structure(tmp_path: Path) -> None:
    schema = Schema(
        path="run",
        children=[
            Dir(
                path="alignments",
                children=[
                    File(path="*.bam", min_matches=2, max_matches=None),
                    File(path="sample_001.bam.bai"),
                ],
            ),
            Dir(
                path="sample_*",
                min_matches=2,
                max_matches=None,
                children=[
                    File(path="results.vcf.gz"),
                    Dir(
                        path="qc",
                        children=[
                            File(path="*.html", min_matches=1, max_matches=2),
                            Dir(
                                path="metrics_*",
                                min_matches=1,
                                max_matches=None,
                                children=[File(path="summary.txt")],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
    run_path = tmp_path / "run"
    alignments_path = run_path / "alignments"
    sample_001_path = run_path / "sample_001"
    sample_002_path = run_path / "sample_002"

    alignments_path.mkdir(parents=True)
    (alignments_path / "sample_001.bam").write_text("bam", encoding="utf-8")
    (alignments_path / "sample_002.bam").write_text("bam", encoding="utf-8")
    (alignments_path / "sample_001.bam.bai").write_text("bai", encoding="utf-8")

    for sample_path in (sample_001_path, sample_002_path):
        metrics_path = sample_path / "qc" / "metrics_run"
        metrics_path.mkdir(parents=True)
        (sample_path / "results.vcf.gz").write_text("vcf", encoding="utf-8")
        (sample_path / "qc" / "report.html").write_text("html", encoding="utf-8")
        (metrics_path / "summary.txt").write_text("summary", encoding="utf-8")

    assert schema.validate_all(run_path) is True
    assert schema.errors == []


def test_schema_aggregates_every_validation_error_subclass(tmp_path: Path) -> None:
    schema = Schema(
        children=[
            Dir(path="missing_dir"),
            File(path="missing_file.txt"),
            Dir(path="missing_sample_*", min_matches=2, max_matches=None),
            File(path="*.txt", max_matches=1),
        ]
    )
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")

    result = schema.validate_all(tmp_path)

    assert result is False
    assert [type(error) for error in schema.errors] == [
        DirectoryMissingError,
        FileMissingError,
        MinMatchError,
        MaxMatchError,
    ]
    assert [error.path for error in schema.errors] == [
        tmp_path / "missing_dir",
        tmp_path / "missing_file.txt",
        tmp_path / "missing_sample_*",
        tmp_path / "*.txt",
    ]


def test_schema_uses_instance_path_when_root_path_is_none(tmp_path: Path) -> None:
    schema = Schema(path=tmp_path / "run", children=[File(path="results.txt")])
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "results.txt").write_text("results", encoding="utf-8")

    assert schema.validate_all(None) is True
    assert schema.errors == []


def test_schema_root_path_arg_takes_precedence_over_instance_path(
    tmp_path: Path,
) -> None:
    schema = Schema(
        path=tmp_path / "missing",
        children=[File(path="results.txt")],
    )
    (tmp_path / "override").mkdir()
    (tmp_path / "override" / "results.txt").write_text("results", encoding="utf-8")

    assert schema.validate_all(tmp_path / "override") is True
    assert schema.errors == []


def test_schema_accepts_absolute_root_path(tmp_path: Path) -> None:
    schema = Schema(children=[File(path="results.txt")])
    (tmp_path / "results.txt").write_text("results", encoding="utf-8")

    assert schema.validate_all(tmp_path) is True
    assert schema.errors == []


def test_schema_accepts_relative_root_path_from_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = Schema(children=[File(path="results.txt")])
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "results.txt").write_text("results", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert schema.validate_all("run") is True
    assert schema.errors == []


def test_schema_resolves_root_path_with_dot_and_dot_dot_segments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schema = Schema(children=[File(path="results.txt")])
    (tmp_path / "runs" / "run_001").mkdir(parents=True)
    (tmp_path / "runs" / "run_001" / "results.txt").write_text(
        "results", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)

    assert schema.validate_all("runs/./archive/../run_001") is True
    assert schema.errors == []


def test_schema_clears_previous_errors_before_revalidating(tmp_path: Path) -> None:
    schema = Schema(children=[File(path="results.txt")])

    assert schema.validate_all(tmp_path) is False
    assert [type(error) for error in schema.errors] == [FileMissingError]
    assert [error.path for error in schema.errors] == [tmp_path / "results.txt"]

    (tmp_path / "results.txt").write_text("results", encoding="utf-8")

    assert schema.validate_all(tmp_path) is True
    assert schema.errors == []


def test_file_not_empty_rule_returns_none_for_non_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("content", encoding="utf-8")
    file_node = File(path="data.txt")
    rule = FileNotEmptyRule()

    assert rule.validate(file_node, path) == []


def test_file_not_empty_rule_returns_file_empty_error_for_empty_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.txt"
    path.write_text("", encoding="utf-8")
    file_node = File(path="data.txt")
    rule = FileNotEmptyRule()

    errors = rule.validate(file_node, path)

    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, FileEmptyError)
    assert error.error_type == "content"
    assert error.node is file_node
    assert error.path == path


def test_csv_schema_rule_returns_empty_list_for_valid_csv(tmp_path: Path) -> None:
    class Row(BaseModel):
        id: int
        name: str

    path = tmp_path / "data.csv"
    path.write_text("id,name\n1,Alice\n2,Bob\n", encoding="utf-8")
    file_node = File(path="data.csv")
    rule = CSVSchemaRule(Row)

    result = rule.validate(file_node, path)

    assert result == []


def test_csv_schema_rule_returns_content_schema_errors_for_invalid_csv(
    tmp_path: Path,
) -> None:
    class Row(BaseModel):
        id: int
        name: str

    path = tmp_path / "data.csv"
    path.write_text("id,name\nnot_an_int,Alice\n", encoding="utf-8")
    file_node = File(path="data.csv")
    rule = CSVSchemaRule(Row)

    result = rule.validate(file_node, path)

    assert len(result) >= 1
    assert all(isinstance(e, ContentSchemaError) for e in result)
    assert all(e.node is file_node for e in result)
    assert all(e.path == path for e in result)
    assert all(e.error_type == "content" for e in result)


def test_schema_validate_all_collects_content_errors(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    path.write_text("", encoding="utf-8")
    schema = Schema(
        children=[File(path="data.txt", content_rules=[FileNotEmptyRule()])]
    )

    result = schema.validate_all(tmp_path)

    assert result is False
    assert len(schema.errors) == 1
    assert isinstance(schema.errors[0], FileEmptyError)


def test_schema_validate_all_clears_content_errors_on_revalidation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "data.txt"
    path.write_text("", encoding="utf-8")
    schema = Schema(
        children=[File(path="data.txt", content_rules=[FileNotEmptyRule()])]
    )

    schema.validate_all(tmp_path)
    assert len(schema.errors) == 1

    path.write_text("now has content", encoding="utf-8")
    result = schema.validate_all(tmp_path)

    assert result is True
    assert schema.errors == []


def test_file_empty_error_message_and_str(tmp_path: Path) -> None:
    path = tmp_path / "data.txt"
    file_node = File(path="data.txt")
    error = FileEmptyError(file_node, path)

    assert error.error_type == "content"
    assert error.get_message() == "File is empty"
    assert str(path) in str(error)


def test_csv_schema_rule_returns_errors_for_multiple_invalid_rows(
    tmp_path: Path,
) -> None:
    class Row(BaseModel):
        id: int
        name: str

    path = tmp_path / "data.csv"
    path.write_text("id,name\nnot_an_int,Alice\nalso_not_int,Bob\n", encoding="utf-8")
    file_node = File(path="data.csv")
    rule = CSVSchemaRule(Row)

    result = rule.validate(file_node, path)

    assert len(result) >= 1
    assert all(isinstance(e, ContentSchemaError) for e in result)
    total_failure_cases = sum(
        len(e.schema_error.failure_cases)
        for e in result
        if e.schema_error.failure_cases is not None
    )
    assert total_failure_cases >= 2


def test_csv_schema_rule_returns_errors_for_missing_column(tmp_path: Path) -> None:
    class Row(BaseModel):
        id: int
        name: str

    path = tmp_path / "data.csv"
    path.write_text("id\n1\n2\n", encoding="utf-8")
    file_node = File(path="data.csv")
    rule = CSVSchemaRule(Row)

    result = rule.validate(file_node, path)

    assert len(result) >= 1
    assert all(isinstance(e, ContentSchemaError) for e in result)


def test_content_schema_error_get_message_is_non_empty_string(tmp_path: Path) -> None:
    class Row(BaseModel):
        id: int

    path = tmp_path / "data.csv"
    path.write_text("id\nnot_an_int\n", encoding="utf-8")
    file_node = File(path="data.csv")
    rule = CSVSchemaRule(Row)

    errors = rule.validate(file_node, path)

    assert len(errors) >= 1
    message = errors[0].get_message()
    assert isinstance(message, str)
    assert len(message) > 0
    assert message != "Unknown schema error"


def test_schema_validate_all_with_csv_schema_rule_passes_for_valid_csv(
    tmp_path: Path,
) -> None:
    class Row(BaseModel):
        id: int
        value: float

    path = tmp_path / "data.csv"
    path.write_text("id,value\n1,1.5\n2,2.5\n", encoding="utf-8")
    schema = Schema(
        children=[File(path="data.csv", content_rules=[CSVSchemaRule(Row)])]
    )

    result = schema.validate_all(tmp_path)

    assert result is True
    assert schema.errors == []


def test_schema_validate_all_with_csv_schema_rule_fails_for_invalid_csv(
    tmp_path: Path,
) -> None:
    class Row(BaseModel):
        id: int

    path = tmp_path / "data.csv"
    path.write_text("id\nnot_an_int\n", encoding="utf-8")
    schema = Schema(
        children=[File(path="data.csv", content_rules=[CSVSchemaRule(Row)])]
    )

    result = schema.validate_all(tmp_path)

    assert result is False
    assert any(isinstance(e, ContentSchemaError) for e in schema.errors)


def test_file_validate_content_aggregates_errors_from_multiple_rules(
    tmp_path: Path,
) -> None:
    (tmp_path / "data.txt").write_text("content", encoding="utf-8")

    class AlwaysFail(ContentRule):
        def __init__(self, tag: str) -> None:
            self.tag = tag

        def validate(self, node: Node, path: Path) -> list[ContentValidationError]:
            return [ContentValidationError(node, path)]

    file_node = File(path="data.txt", content_rules=[AlwaysFail("a"), AlwaysFail("b")])
    file_node.validate_structure(tmp_path)
    errors = file_node.validate_content()

    assert len(errors) == 2
    assert all(isinstance(e, ContentValidationError) for e in errors)


def test_file_validate_content_reports_error_only_for_empty_file_in_glob(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.csv").write_text("", encoding="utf-8")
    (tmp_path / "b.csv").write_text("data", encoding="utf-8")

    file_node = File(
        path="*.csv",
        min_matches=2,
        max_matches=None,
        content_rules=[FileNotEmptyRule()],
    )
    file_node.validate_structure(tmp_path)
    errors = file_node.validate_content()

    assert len(errors) == 1
    assert isinstance(errors[0], FileEmptyError)
    assert errors[0].path == (tmp_path / "a.csv").resolve()


def test_file_validate_content_raises_if_validate_structure_not_called() -> None:
    file_node = File(path="results.txt")
    with pytest.raises(RuntimeError, match="validate_structure\\(\\) must be called"):
        file_node.validate_content()


def test_dir_missing_with_file_children_does_not_raise(tmp_path: Path) -> None:
    schema = Schema(
        children=[
            Dir(
                path="missing_dir",
                children=[File(path="data.csv")],
            )
        ]
    )
    result = schema.validate_all(tmp_path)
    assert result is False
    assert len(schema.errors) == 1
    assert isinstance(schema.errors[0], DirectoryMissingError)
