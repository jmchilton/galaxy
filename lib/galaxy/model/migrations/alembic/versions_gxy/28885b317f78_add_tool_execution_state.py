"""Add tool_execution_state table, execution-state FKs, and backfill from tool_request.

A tool execution's validated request_internal payload now lives on its own
table (``tool_execution_state``) instead of being co-located with the
command-side ``ToolRequest.request`` column. ``ToolRequest``, ``Job`` and
``WorkflowInvocationStep`` each get a nullable FK at it, so consumers
(History Graph, structured workflow extraction) walk one source-neutral
seam: ``Job -> tool_execution_state``.

``state`` is the validity of the capture (not_validated / validated /
validation_failed), deliberately distinct from ``ToolRequest.state``
(command lifecycle) and ``WorkflowInvocationStep.state``
(invocation-step lifecycle).

Backfill (tool-request path only): every existing ``tool_request`` row gets
a matching ``tool_execution_state`` row with ``state='validated'`` (the
request was validated at API ingestion regardless of its later command
lifecycle state) and the same ``request`` payload, reusing ``tool_request.id``
as ``tool_execution_state.id`` for a 1:1 mapping safe to express because the
new table is empty pre-backfill. ``tool_request.tool_execution_state_id`` and
every ``job.tool_execution_state_id`` joined to a tool_request are pointed at
the new row so the resolver's unified ``Job -> tool_execution_state`` walk
works for historical tool-request executions. Workflow-produced historical
rows have no tool_request and no tool_execution_state link; the resolver
correctly returns None for them and the caller degrades to legacy state, as
today. After backfill the PostgreSQL id sequence is advanced past the
highest backfilled id so new mints do not collide.

Revision ID: 28885b317f78
Revises: 0b49ffb1e890
Create Date: 2026-05-17 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

from galaxy.model.custom_types import JSONType
from galaxy.model.database_object_names import (
    build_foreign_key_name,
    build_index_name,
)
from galaxy.model.migrations.util import (
    add_column,
    create_foreign_key,
    create_index,
    create_table,
    drop_column,
    drop_constraint,
    drop_index,
    drop_table,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "28885b317f78"
down_revision = "0b49ffb1e890"
branch_labels = None
depends_on = None

execution_state_table = "tool_execution_state"
fk_column = "tool_execution_state_id"

referring_tables = ("tool_request", "job", "workflow_invocation_step")


def upgrade():
    with transaction():
        create_table(
            execution_state_table,
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("create_time", sa.DateTime),
            sa.Column("update_time", sa.DateTime),
            sa.Column("request", JSONType),
            sa.Column("state", sa.String(32), index=True),
        )
        for table in referring_tables:
            _add_fk(table)
        _backfill_from_tool_request()


def downgrade():
    with transaction():
        for table in reversed(referring_tables):
            _drop_fk(table)
        drop_table(execution_state_table)


def _add_fk(table: str) -> None:
    add_column(table, sa.Column(fk_column, sa.Integer, nullable=True, default=None))
    create_index(build_index_name(table, fk_column), table, [fk_column])
    create_foreign_key(
        build_foreign_key_name(table, fk_column),
        table,
        execution_state_table,
        [fk_column],
        ["id"],
    )


def _drop_fk(table: str) -> None:
    drop_constraint(build_foreign_key_name(table, fk_column), table)
    drop_index(build_index_name(table, fk_column), table)
    drop_column(table, fk_column)


def _backfill_from_tool_request() -> None:
    """Mint one tool_execution_state row per existing tool_request, reusing
    tool_request.id as tool_execution_state.id (safe because the table is
    new and empty). Link tool_request and joined jobs at the new row, then
    advance the PostgreSQL id sequence past the backfilled max.

    Skips rows whose request payload is NULL (model says non-null; the
    guard is defensive against historical anomalies). The tool-request
    payload is treated as validated by definition: it passed API-side
    validation at ingestion regardless of where the command lifecycle
    later landed (NEW / SUBMITTED / FAILED). The historical state column
    on tool_request is not consulted by the resolver and is unchanged."""
    op.execute(
        "INSERT INTO tool_execution_state (id, request, state, create_time, update_time) "
        "SELECT id, request, 'validated', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM tool_request WHERE request IS NOT NULL"
    )
    op.execute("UPDATE tool_request SET tool_execution_state_id = id WHERE request IS NOT NULL")
    # Gate Job linkage on TES presence rather than tool_request_id presence
    # so we never produce a dangling FK when the source tool_request was
    # skipped (e.g. a historical row whose request column is NULL).
    op.execute(
        "UPDATE job SET tool_execution_state_id = tool_request_id "
        "WHERE tool_request_id IN (SELECT id FROM tool_execution_state)"
    )
    if op.get_bind().dialect.name == "postgresql":
        # setval(seq, MAX(id)) -> nextval returns MAX(id)+1. The HAVING
        # clause makes the SELECT empty when the table had no rows (MAX
        # is NULL), so setval is not called with NULL.
        op.execute(
            "SELECT setval(pg_get_serial_sequence('tool_execution_state', 'id'), MAX(id)) "
            "FROM tool_execution_state HAVING MAX(id) IS NOT NULL"
        )
