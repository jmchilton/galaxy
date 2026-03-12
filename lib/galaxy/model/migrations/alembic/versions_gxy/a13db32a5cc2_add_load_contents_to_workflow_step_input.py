"""Add load_contents to workflow_step_input

Revision ID: a13db32a5cc2
Revises: 7c300d2a5a5e
Create Date: 2026-03-12 00:00:00.000000
"""

import sqlalchemy as sa

from galaxy.model.migrations.util import (
    add_column,
    drop_column,
)

revision = "a13db32a5cc2"
down_revision = "7c300d2a5a5e"
branch_labels = None
depends_on = None

table_name = "workflow_step_input"
column_name = "load_contents"


def upgrade():
    add_column(table_name, sa.Column(column_name, sa.Boolean, nullable=True))


def downgrade():
    drop_column(table_name, column_name)
