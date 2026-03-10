"""Add source_index to workflow_output

Revision ID: 7c300d2a5a5e
Revises: fb16d09348db
Create Date: 2026-03-10 00:00:00.000000
"""

import sqlalchemy as sa

from galaxy.model.migrations.util import (
    add_column,
    drop_column,
)

revision = "7c300d2a5a5e"
down_revision = "566b691307a5"
branch_labels = None
depends_on = None

table_name = "workflow_output"
column_name = "source_index"


def upgrade():
    add_column(table_name, sa.Column(column_name, sa.Integer, nullable=True))


def downgrade():
    drop_column(table_name, column_name)
