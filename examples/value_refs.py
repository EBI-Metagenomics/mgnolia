"""Use a measured row count as another node's match limit."""

from mgnolia import File, Schema, Value
from mgnolia.content import RowCountRule


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

if not schema.validate_all("."):
    for error in schema.errors:
        print(error)
