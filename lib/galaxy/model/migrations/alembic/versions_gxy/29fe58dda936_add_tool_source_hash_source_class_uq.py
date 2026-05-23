"""Dedupe ``tool_source`` by content + identity and add a unique constraint.

Existing dev DBs accumulated many ``tool_source`` rows from the async
tool-request mint path with ``hash="TODO"`` (literal placeholder, never
filled in). Once the mint path switches to a content-addressable
lookup-or-create helper, only one row per
``(hash, source_class, identity_hash)`` should exist. Pre-dedupe so the
unique constraint can be added without conflict.

Dedupe collapses each content + identity group onto the minimum-id survivor:
``tool_request.tool_source_id`` references are repointed at the survivor, then
loser rows are deleted. The constraint is then added.

Downgrade drops the constraint; it does not un-dedupe.

Revision ID: 29fe58dda936
Revises: 28885b317f78
Create Date: 2026-05-23 00:00:00.000000

"""

import hashlib

import sqlalchemy as sa
from alembic import op

from galaxy.model.migrations.util import (
    add_column,
    alter_column,
    create_unique_constraint,
    drop_column,
    drop_constraint,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "29fe58dda936"
down_revision = "28885b317f78"
branch_labels = None
depends_on = None


def upgrade():
    with transaction():
        add_column("tool_source", sa.Column("identity_hash", sa.String(255), nullable=True))
        _backfill_identity_hash()
        alter_column("tool_source", "identity_hash", nullable=False)
        _dedupe_tool_source()
        create_unique_constraint(
            "uq_tool_source_hash_source_class_identity_hash",
            "tool_source",
            ["hash", "source_class", "identity_hash"],
        )


def downgrade():
    with transaction():
        drop_constraint("uq_tool_source_hash_source_class_identity_hash", "tool_source")
        drop_column("tool_source", "identity_hash")


def _backfill_identity_hash() -> None:
    conn = op.get_bind()
    rows = list(
        conn.execute(
            sa.text("SELECT id, tool_id, tool_version, dynamic_tool_id FROM tool_source ORDER BY id")
        ).mappings()
    )
    for row in rows:
        identity_hash = _identity_hash_for_row(row)
        conn.execute(
            sa.text("UPDATE tool_source SET identity_hash = :identity_hash WHERE id = :id"),
            {"identity_hash": identity_hash, "id": row["id"]},
        )


def _identity_hash_for_row(row) -> str:
    dynamic_tool_id = row["dynamic_tool_id"]
    if dynamic_tool_id is not None:
        identity = ("dynamic", str(dynamic_tool_id))
    else:
        identity = ("static", row["tool_id"] or "", row["tool_version"] or "")
    return hashlib.sha256("\0".join(identity).encode("utf-8")).hexdigest()


def _dedupe_tool_source() -> None:
    """Repoint ``tool_request.tool_source_id`` at the minimum-id row per
    content + identity group, then delete the loser rows. SQL is
    written to work on both PostgreSQL and SQLite (correlated subqueries
    only — no UPDATE...FROM, no window functions in DELETE)."""
    op.execute("""
        UPDATE tool_request
        SET tool_source_id = (
            SELECT MIN(ts2.id) FROM tool_source ts2
            WHERE ts2.hash = (
                SELECT ts1.hash FROM tool_source ts1
                WHERE ts1.id = tool_request.tool_source_id
            )
            AND ts2.source_class = (
                SELECT ts1.source_class FROM tool_source ts1
                WHERE ts1.id = tool_request.tool_source_id
            )
            AND ts2.identity_hash = (
                SELECT ts1.identity_hash FROM tool_source ts1
                WHERE ts1.id = tool_request.tool_source_id
            )
        )
        WHERE tool_source_id IN (
            SELECT id FROM tool_source ts
            WHERE EXISTS (
                SELECT 1 FROM tool_source ts2
                WHERE ts2.hash = ts.hash
                  AND ts2.source_class = ts.source_class
                  AND ts2.identity_hash = ts.identity_hash
                  AND ts2.id < ts.id
            )
        )
        """)
    op.execute("""
        DELETE FROM tool_source
        WHERE id IN (
            SELECT id FROM tool_source ts
            WHERE EXISTS (
                SELECT 1 FROM tool_source ts2
                WHERE ts2.hash = ts.hash
                  AND ts2.source_class = ts.source_class
                  AND ts2.identity_hash = ts.identity_hash
                  AND ts2.id < ts.id
            )
        )
        """)
