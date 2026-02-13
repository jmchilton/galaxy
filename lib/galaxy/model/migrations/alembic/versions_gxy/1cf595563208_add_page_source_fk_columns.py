"""add page source FK columns

Revision ID: 1cf595563208
Revises: b75f0f4dbcd4
Create Date: 2025-01-07

"""

import sqlalchemy as sa

from galaxy.model.migrations.util import (
    add_column,
    create_foreign_key,
    create_index,
    drop_column,
    drop_constraint,
    drop_index,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "1cf595563208"
down_revision = "b75f0f4dbcd4"
branch_labels = None
depends_on = None


def upgrade():
    with transaction():
        add_column("page", sa.Column("source_invocation_id", sa.Integer, nullable=True))
        add_column("page", sa.Column("source_history_notebook_id", sa.Integer, nullable=True))

        create_index("ix_page_source_invocation_id", "page", ["source_invocation_id"])
        create_index("ix_page_source_history_notebook_id", "page", ["source_history_notebook_id"])

        create_foreign_key(
            "page_source_invocation_id_fkey",
            "page",
            "workflow_invocation",
            ["source_invocation_id"],
            ["id"],
        )
        create_foreign_key(
            "page_source_history_notebook_id_fkey",
            "page",
            "history_notebook",
            ["source_history_notebook_id"],
            ["id"],
        )


def downgrade():
    with transaction():
        drop_constraint("page_source_history_notebook_id_fkey", "page")
        drop_constraint("page_source_invocation_id_fkey", "page")
        drop_index("ix_page_source_history_notebook_id", "page")
        drop_index("ix_page_source_invocation_id", "page")
        drop_column("page", "source_history_notebook_id")
        drop_column("page", "source_invocation_id")
