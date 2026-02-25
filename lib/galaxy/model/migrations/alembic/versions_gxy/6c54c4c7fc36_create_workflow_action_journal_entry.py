"""Create workflow_action_journal_entry table

Revision ID: 6c54c4c7fc36
Revises: 566b691307a5
Create Date: 2026-02-25
"""

import sqlalchemy as sa
from sqlalchemy.sql import func

from galaxy.model.custom_types import JSONType
from galaxy.model.migrations.util import (
    create_table,
    drop_table,
)

revision = "6c54c4c7fc36"
down_revision = "566b691307a5"
branch_labels = None
depends_on = None


def upgrade():
    create_table(
        "workflow_action_journal_entry",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("create_time", sa.DateTime, nullable=True, server_default=func.now()),
        sa.Column("update_time", sa.DateTime, nullable=True, server_default=func.now()),
        sa.Column("stored_workflow_id", sa.Integer, sa.ForeignKey("stored_workflow.id"), index=True, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("galaxy_user.id"), index=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_action_type", sa.String(255), nullable=True),
        sa.Column("action_payloads", JSONType, nullable=True),
        sa.Column("workflow_id_before", sa.Integer, sa.ForeignKey("workflow.id"), nullable=False),
        sa.Column("workflow_id_after", sa.Integer, sa.ForeignKey("workflow.id"), nullable=False),
        sa.Column("execution_messages", JSONType, nullable=True),
        sa.Column("is_revert", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "reverted_entry_id",
            sa.Integer,
            sa.ForeignKey("workflow_action_journal_entry.id"),
            nullable=True,
        ),
    )


def downgrade():
    drop_table("workflow_action_journal_entry")
