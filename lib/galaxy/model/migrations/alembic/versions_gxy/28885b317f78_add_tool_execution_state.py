"""Add tool_execution_state table, execution-state FKs, and backfill from tool_request.

A tool execution's validated request_internal payload lives on its own
table (``tool_execution_state``) instead of being co-located with the
command-side ``ToolRequest.request`` column. ``ToolRequest``, ``Job``,
``WorkflowInvocationStep`` and ``ImplicitCollectionJobs`` each get a
nullable FK at it, so consumers (History Graph, structured workflow
extraction) walk one source-neutral seam.

``state`` is the validity of the capture (not_validated / validated /
validation_failed), deliberately distinct from ``ToolRequest.state``
(command lifecycle) and ``WorkflowInvocationStep.state``
(invocation-step lifecycle).

Backfill (tool-request path only): every existing ``tool_request`` row
mints a matching ``tool_execution_state`` row with ``state='validated'``
and the same payload, reusing ``tool_request.id`` as
``tool_execution_state.id`` for a 1:1 mapping safe to express because
the new table is empty pre-backfill. The TES FK is then set on
``tool_request``, every joined ``job`` that the tool_request produced,
and every ``implicit_collection_jobs`` whose constituent jobs share
that TES. Workflow-produced historical rows have no tool_request and
no TES link; the resolver returns None for them. After backfill the
PostgreSQL id sequence is advanced past the highest backfilled id so
new mints do not collide.

After the backfill the ``tool_request.request`` column is dropped:
the TES row is now the only payload carrier and the dual-write was
purely transitional.

The Job-side TES FK is canonical only for jobs not under an ICJ; for
mapped executions the ICJ carries the link. The strict-check
invariant in lib/galaxy/model/__init__.py enforces "exactly one path"
in tests.

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

revision = "28885b317f78"
down_revision = "0b49ffb1e890"
branch_labels = None
depends_on = None

execution_state_table = "tool_execution_state"
fk_column = "tool_execution_state_id"

referring_tables = (
    "tool_request",
    "job",
    "workflow_invocation_step",
    "implicit_collection_jobs",
)


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
        _drop_tool_request_request_column()


def downgrade():
    with transaction():
        _restore_tool_request_request_column()
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
    new and empty). Link tool_request, joined jobs, and any
    implicit_collection_jobs whose jobs share that TES at the new row,
    then advance the PostgreSQL id sequence past the backfilled max.

    Skips rows whose request payload is NULL. The tool-request payload
    is treated as validated by definition: it passed API-side validation
    at ingestion regardless of where the command lifecycle later landed.
    """
    op.execute(
        "INSERT INTO tool_execution_state (id, request, state, create_time, update_time) "
        "SELECT id, request, 'validated', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM tool_request WHERE request IS NOT NULL"
    )
    op.execute("UPDATE tool_request SET tool_execution_state_id = id WHERE request IS NOT NULL")
    op.execute(
        "UPDATE job SET tool_execution_state_id = tool_request_id "
        "WHERE tool_request_id IN (SELECT id FROM tool_execution_state)"
    )
    # Backfill ICJ FK from constituent jobs: when every job in an ICJ
    # shares a single non-null TES id, copy it to the ICJ. ICJs whose
    # jobs disagree on TES (which should not happen under correct
    # write-side discipline) stay null. Use a correlated subquery shape
    # that both Postgres and SQLite execute.
    op.execute(
        "UPDATE implicit_collection_jobs SET tool_execution_state_id = ("
        "  SELECT MIN(j.tool_execution_state_id) "
        "  FROM implicit_collection_jobs_job_association a "
        "  JOIN job j ON j.id = a.job_id "
        "  WHERE a.implicit_collection_jobs_id = implicit_collection_jobs.id "
        "    AND j.tool_execution_state_id IS NOT NULL "
        "  GROUP BY a.implicit_collection_jobs_id "
        "  HAVING COUNT(DISTINCT j.tool_execution_state_id) = 1"
        ")"
    )
    # Drop the now-redundant Job FK for jobs under an ICJ.
    op.execute(
        "UPDATE job SET tool_execution_state_id = NULL "
        "WHERE id IN ("
        "  SELECT a.job_id FROM implicit_collection_jobs_job_association a "
        "  JOIN implicit_collection_jobs icj ON icj.id = a.implicit_collection_jobs_id "
        "  WHERE icj.tool_execution_state_id IS NOT NULL"
        ")"
    )
    # Drop the redundant WIS FK when the WIS has a mapped ICJ that
    # already carries the TES link.
    op.execute(
        "UPDATE workflow_invocation_step SET tool_execution_state_id = NULL "
        "WHERE implicit_collection_jobs_id IN ("
        "  SELECT id FROM implicit_collection_jobs WHERE tool_execution_state_id IS NOT NULL"
        ")"
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "SELECT setval(pg_get_serial_sequence('tool_execution_state', 'id'), MAX(id)) "
            "FROM tool_execution_state HAVING MAX(id) IS NOT NULL"
        )


def _drop_tool_request_request_column() -> None:
    """Drop the now-redundant tool_request.request column. Payload lives
    on tool_execution_state.request, reachable via
    ``tool_request.tool_execution_state``.
    """
    drop_column("tool_request", "request")


def _restore_tool_request_request_column() -> None:
    """On downgrade, re-add the column as nullable and copy the payload
    back from the linked TES so existing readers see something.
    """
    add_column("tool_request", sa.Column("request", JSONType, nullable=True))
    op.execute(
        "UPDATE tool_request SET request = ("
        "  SELECT request FROM tool_execution_state "
        "  WHERE tool_execution_state.id = tool_request.tool_execution_state_id"
        ")"
    )
