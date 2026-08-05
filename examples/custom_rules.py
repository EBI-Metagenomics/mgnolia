"""Validate accession-named TSV files with custom rules and a Value/Ref."""

import re
import sys
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
    ],
)

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
if not schema.validate_all(root):
    for error in schema.errors:
        print(error)
