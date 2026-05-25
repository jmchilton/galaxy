"""Move tool_source_id from tool_request to tool_execution_state.

Tool identity belongs to the execution event, not the request side. After
this migration every ``ToolExecutionState`` row carries a NOT NULL
``tool_source_id``; ``ToolRequest`` reaches tool identity via its TES.
Workflow-step TES rows (which never had a tool_request) now also gain a
``ToolSource`` reference (populated by the writer in workflow/modules.py).

Any pre-existing workflow-step TES row that lacks a path to a ToolSource
is dev-only data on this unreleased branch and is deleted during upgrade;
its referencing ``workflow_invocation_step`` link is cleared.

Backfill is direct because ``28885b317f78`` minted TES rows 1:1 with
tool_request rows.

Revision ID: 395148707459
Revises: 29fe58dda936
Create Date: 2026-05-25 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from galaxy.model.database_object_names import (
    build_foreign_key_name,
    build_index_name,
)
from galaxy.model.migrations.util import (
    add_column,
    alter_column,
    create_foreign_key,
    create_index,
    drop_column,
    drop_constraint,
    drop_index,
    transaction,
)

revision = "395148707459"
down_revision = "29fe58dda936"
branch_labels = None
depends_on = None

tes_table = "tool_execution_state"
tr_table = "tool_request"
ts_table = "tool_source"
fk_column = "tool_source_id"

tes_index_name = build_index_name(tes_table, fk_column)
tes_fk_name = build_foreign_key_name(tes_table, fk_column)
tr_index_name = build_index_name(tr_table, fk_column)
tr_fk_name = build_foreign_key_name(tr_table, fk_column)


def upgrade():
    with transaction():
        add_column(tes_table, sa.Column(fk_column, sa.Integer, nullable=True, default=None))
        create_index(tes_index_name, tes_table, [fk_column])
        create_foreign_key(tes_fk_name, tes_table, ts_table, [fk_column], ["id"])
        _backfill_tes_from_tool_request()
        _delete_orphan_tes_rows()
        alter_column(tes_table, fk_column, nullable=False)
        drop_constraint(tr_fk_name, tr_table)
        drop_index(tr_index_name, tr_table)
        drop_column(tr_table, fk_column)


def downgrade():
    with transaction():
        add_column(tr_table, sa.Column(fk_column, sa.Integer, nullable=True, default=None))
        create_index(tr_index_name, tr_table, [fk_column])
        create_foreign_key(tr_fk_name, tr_table, ts_table, [fk_column], ["id"])
        _backfill_tool_request_from_tes()
        drop_constraint(tes_fk_name, tes_table)
        drop_index(tes_index_name, tes_table)
        drop_column(tes_table, fk_column)


def _backfill_tes_from_tool_request() -> None:
    """Copy tool_source_id from each tool_request to its linked TES."""
    op.execute(
        "UPDATE tool_execution_state SET tool_source_id = ("
        "  SELECT tool_request.tool_source_id "
        "  FROM tool_request "
        "  WHERE tool_request.tool_execution_state_id = tool_execution_state.id "
        "  LIMIT 1"
        ") "
        "WHERE EXISTS ("
        "  SELECT 1 FROM tool_request "
        "  WHERE tool_request.tool_execution_state_id = tool_execution_state.id"
        ")"
    )


def _delete_orphan_tes_rows() -> None:
    """Drop TES rows still NULL after backfill. The only producer that
    can leave one in this state is a pre-this-branch workflow-step
    capture that ran without identity persistence. Clear the WIS link
    first so the FK delete is unambiguous, then delete the TES row.
    """
    op.execute(
        "UPDATE workflow_invocation_step SET tool_execution_state_id = NULL "
        "WHERE tool_execution_state_id IN ("
        "  SELECT id FROM tool_execution_state WHERE tool_source_id IS NULL"
        ")"
    )
    op.execute("DELETE FROM tool_execution_state WHERE tool_source_id IS NULL")


def _backfill_tool_request_from_tes() -> None:
    op.execute(
        "UPDATE tool_request SET tool_source_id = ("
        "  SELECT tool_source_id FROM tool_execution_state "
        "  WHERE tool_execution_state.id = tool_request.tool_execution_state_id"
        ") "
        "WHERE tool_execution_state_id IS NOT NULL"
    )
