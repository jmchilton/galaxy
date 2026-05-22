"""Add tool_request.request_state + UNIQUE(tool_source.hash, source_class).

``tool_request.request_state`` records the validity of the captured request
payload (``not_validated`` / ``validated`` / ``validation_failed``). Distinct
from ``tool_request.state``, which tracks the async-submission lifecycle.
Set whenever a ToolRequest is minted (async API or workflow tool step).

The ToolSource unique constraint enables content-addressable lookup-or-create:
the same persisted tool source (XML/JSON) under the same parser class always
maps to one row, regardless of how many ToolRequests reference it.

Revision ID: 28885b317f78
Revises: 6925fe4c8a17
Create Date: 2026-05-21 12:30:00.000000

"""

from alembic import op
from sqlalchemy import (
    Column,
    String,
)

from galaxy.model.migrations.util import (
    add_column,
    drop_column,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "28885b317f78"
down_revision = "6925fe4c8a17"
branch_labels = None
depends_on = None


def upgrade():
    with transaction():
        add_column("tool_request", Column("request_state", String(32)))
        op.create_unique_constraint(
            "uq_tool_source_hash_source_class",
            "tool_source",
            ["hash", "source_class"],
        )


def downgrade():
    with transaction():
        op.drop_constraint("uq_tool_source_hash_source_class", "tool_source", type_="unique")
        drop_column("tool_request", "request_state")
