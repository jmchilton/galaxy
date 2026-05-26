"""Replace TRICA with TES-keyed TEICA; constrain TES back-pops to 1..[0,1].

``tool_request_implicit_collection_association`` (TRICA) is replaced by
``tool_execution_implicit_collection_association`` (TEICA), keyed on
``tool_execution_state_id`` instead of ``tool_request_id``. TES is the
canonical per-execution anchor; rekeying makes the table forward-
compatible with classic Job paths that also populate TES.

The TR-keyed rows are backfilled into TEICA via
``ToolRequest.tool_execution_state_id`` before TRICA is dropped, so no
production data is lost. Downgrade re-creates TRICA and backfills back
via TES -> TR.

Adds a UNIQUE constraint on ``tool_execution_state_id`` for each of
``tool_request``, ``job``, ``implicit_collection_jobs`` and
``workflow_invocation_step``. PostgreSQL and SQLite both permit multiple
NULLs under UNIQUE, so rows without a TES link remain legal (Jobs under
an ICJ, import-path ICJs without TES, history-import WIS rows).

Revision ID: 10c4cd393d5a
Revises: 395148707459
Create Date: 2026-05-25 00:00:00.000000

"""

from alembic import op
from sqlalchemy import (
    Column,
    Integer,
    String,
)

from galaxy.model.migrations.util import (
    create_foreign_key,
    create_table,
    create_unique_constraint,
    drop_constraint,
    drop_table,
    transaction,
)

revision = "10c4cd393d5a"
down_revision = "395148707459"
branch_labels = None
depends_on = None

trica_table = "tool_request_implicit_collection_association"
teica_table = "tool_execution_implicit_collection_association"

_unique_tables = (
    "tool_request",
    "job",
    "implicit_collection_jobs",
    "workflow_invocation_step",
)


def _uq_name(table: str) -> str:
    return f"uq_{table}_tool_execution_state_id"


def upgrade():
    with transaction():
        create_table(
            teica_table,
            Column("id", Integer, primary_key=True),
            Column("tool_execution_state_id", Integer, index=True, nullable=False),
            Column("dataset_collection_id", Integer, index=True, nullable=False),
            Column("output_name", String(255), nullable=False),
        )
        create_foreign_key(
            "fk_teica_tesi",
            teica_table,
            "tool_execution_state",
            ["tool_execution_state_id"],
            ["id"],
        )
        create_foreign_key(
            "fk_teica_dci",
            teica_table,
            "history_dataset_collection_association",
            ["dataset_collection_id"],
            ["id"],
        )
        _backfill_teica_from_trica()
        drop_table(trica_table)
        for table in _unique_tables:
            create_unique_constraint(_uq_name(table), table, ["tool_execution_state_id"])


def downgrade():
    with transaction():
        for table in _unique_tables:
            drop_constraint(_uq_name(table), table)
        create_table(
            trica_table,
            Column("id", Integer, primary_key=True),
            Column("tool_request_id", Integer, index=True),
            Column("dataset_collection_id", Integer, index=True),
            Column("output_name", String(255), nullable=False),
        )
        create_foreign_key(
            "fk_trica_tri",
            trica_table,
            "tool_request",
            ["tool_request_id"],
            ["id"],
        )
        create_foreign_key(
            "fk_trica_dci",
            trica_table,
            "history_dataset_collection_association",
            ["dataset_collection_id"],
            ["id"],
        )
        _backfill_trica_from_teica()
        drop_table(teica_table)


def _backfill_teica_from_trica() -> None:
    """Lift TR-keyed rows into TES-keyed rows via TR.tool_execution_state_id.
    Skip rows whose TR has no TES link (pre-EXEC_STATE imports)."""
    op.execute(
        "INSERT INTO tool_execution_implicit_collection_association "
        "(tool_execution_state_id, dataset_collection_id, output_name) "
        "SELECT tr.tool_execution_state_id, trica.dataset_collection_id, trica.output_name "
        "FROM tool_request_implicit_collection_association trica "
        "JOIN tool_request tr ON tr.id = trica.tool_request_id "
        "WHERE tr.tool_execution_state_id IS NOT NULL"
    )


def _backfill_trica_from_teica() -> None:
    """Recover TR-keyed rows from TES-keyed rows via TR.tool_execution_state_id.
    Skip TEICA rows whose TES has no TR (classic Job paths)."""
    op.execute(
        "INSERT INTO tool_request_implicit_collection_association "
        "(tool_request_id, dataset_collection_id, output_name) "
        "SELECT tr.id, teica.dataset_collection_id, teica.output_name "
        "FROM tool_execution_implicit_collection_association teica "
        "JOIN tool_request tr ON tr.tool_execution_state_id = teica.tool_execution_state_id"
    )
