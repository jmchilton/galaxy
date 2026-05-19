"""add tool identity columns to tool_source

Revision ID: 0b49ffb1e890
Revises: b8d5e2f9a1c7
Create Date: 2026-05-19 11:07:21.550126

"""

import sqlalchemy as sa

from galaxy.model.database_object_names import (
    build_foreign_key_name,
    build_index_name,
)
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
revision = "0b49ffb1e890"
down_revision = "b8d5e2f9a1c7"
branch_labels = None
depends_on = None

table_name = "tool_source"

tool_id_column_name = "tool_id"
tool_id_column_index_name = build_index_name(table_name, tool_id_column_name)

tool_version_column_name = "tool_version"

ref_table_name = "dynamic_tool"
dynamic_tool_id_column_name = "dynamic_tool_id"
dynamic_tool_id_column_index_name = build_index_name(table_name, dynamic_tool_id_column_name)
dynamic_tool_id_column_fk_name = build_foreign_key_name(table_name, dynamic_tool_id_column_name)


def upgrade():
    with transaction():
        _add_column_tool_id()
        _add_column_tool_version()
        _add_column_dynamic_tool_id()


def downgrade():
    with transaction():
        _drop_column_dynamic_tool_id()
        _drop_column_tool_version()
        _drop_column_tool_id()


def _add_column_tool_id():
    add_column(
        table_name,
        sa.Column(tool_id_column_name, sa.String(255), nullable=True, default=None),
    )
    create_index(tool_id_column_index_name, table_name, [tool_id_column_name])


def _add_column_tool_version():
    add_column(
        table_name,
        sa.Column(tool_version_column_name, sa.String(255), nullable=True, default=None),
    )


def _add_column_dynamic_tool_id():
    add_column(
        table_name,
        sa.Column(dynamic_tool_id_column_name, sa.Integer, nullable=True, default=None),
    )
    create_index(dynamic_tool_id_column_index_name, table_name, [dynamic_tool_id_column_name])
    create_foreign_key(
        dynamic_tool_id_column_fk_name, table_name, ref_table_name, [dynamic_tool_id_column_name], ["id"]
    )


def _drop_column_tool_id():
    drop_index(tool_id_column_index_name, table_name)
    drop_column(table_name, tool_id_column_name)


def _drop_column_tool_version():
    drop_column(table_name, tool_version_column_name)


def _drop_column_dynamic_tool_id():
    drop_constraint(dynamic_tool_id_column_fk_name, table_name)
    drop_index(dynamic_tool_id_column_index_name, table_name)
    drop_column(table_name, dynamic_tool_id_column_name)
