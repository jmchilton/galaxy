"""add tool license agreement tables

Revision ID: 01cbf54bb541
Revises: 64d49ad328d4
Create Date: 2026-09-29 17:00:00.000000

"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from galaxy.model.custom_types import TrimmedString
from galaxy.model.database_object_names import (
    build_check_constraint_name,
    build_index_name,
    build_unique_constraint_name,
)
from galaxy.model.migrations.util import (
    create_table,
    drop_table,
    transaction,
)

# revision identifiers, used by Alembic.
revision = "01cbf54bb541"
down_revision = "64d49ad328d4"
branch_labels = None
depends_on = None

agreement_table = "tool_license_agreement"
event_table = "tool_license_acceptance_event"
job_association_table = "job_license_acceptance"
invocation_association_table = "workflow_invocation_license_acceptance"


def _agreement_hash_column() -> Column[str]:
    return Column(
        "agreement_hash",
        String(64),
        ForeignKey(f"{agreement_table}.agreement_hash", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )


def upgrade() -> None:
    with transaction():
        create_table(
            agreement_table,
            Column("agreement_hash", String(64), primary_key=True),
            Column("affirmation", Text, nullable=False),
            Column("terms", Text, nullable=False),
            Column("create_time", DateTime, nullable=False),
        )
        create_table(
            event_table,
            Column("id", Integer, primary_key=True),
            Column("user_id", Integer, ForeignKey("galaxy_user.id", ondelete="CASCADE"), nullable=False),
            _agreement_hash_column(),
            Column("action", String(16), nullable=False),
            Column("license_id", TrimmedString(255), nullable=True),
            Column("license_version", TrimmedString(255), nullable=True),
            Column("license_label", TrimmedString(255), nullable=True),
            Column("license_url", Text, nullable=True),
            Column("granted_by", String(16), nullable=False),
            Column(
                "granted_by_user_id",
                Integer,
                ForeignKey("galaxy_user.id", ondelete="SET NULL"),
                index=True,
                nullable=True,
            ),
            Column("prompting_tool_id", TrimmedString(255), nullable=True),
            Column("prompting_tool_version", TrimmedString(255), nullable=True),
            Column("create_time", DateTime, nullable=False),
            CheckConstraint("action IN ('accept', 'revoke')", name=build_check_constraint_name(event_table, "action")),
            CheckConstraint(
                "granted_by IN ('user', 'admin')", name=build_check_constraint_name(event_table, "granted_by")
            ),
            Index(
                build_index_name(event_table, ["user_id", "agreement_hash", "id"]), "user_id", "agreement_hash", "id"
            ),
        )
        create_table(
            job_association_table,
            Column("id", Integer, primary_key=True),
            Column("job_id", Integer, ForeignKey("job.id", ondelete="CASCADE"), nullable=False),
            Column(
                "acceptance_event_id",
                Integer,
                ForeignKey(f"{event_table}.id", ondelete="SET NULL"),
                index=True,
                nullable=True,
            ),
            _agreement_hash_column(),
            Column("authorization_kind", String(16), nullable=False),
            CheckConstraint(
                "authorization_kind IN ('persistent', 'one_time')",
                name=build_check_constraint_name(job_association_table, "authorization_kind"),
            ),
            UniqueConstraint(
                "job_id",
                "agreement_hash",
                name=build_unique_constraint_name(job_association_table, ["job_id", "agreement_hash"]),
            ),
        )
        create_table(
            invocation_association_table,
            Column("id", Integer, primary_key=True),
            Column(
                "workflow_invocation_id",
                Integer,
                ForeignKey("workflow_invocation.id", ondelete="CASCADE"),
                nullable=False,
            ),
            _agreement_hash_column(),
            Column("create_time", DateTime, nullable=False),
            UniqueConstraint(
                "workflow_invocation_id",
                "agreement_hash",
                name=build_unique_constraint_name(
                    invocation_association_table, ["workflow_invocation_id", "agreement_hash"]
                ),
            ),
        )


def downgrade() -> None:
    with transaction():
        drop_table(invocation_association_table)
        drop_table(job_association_table)
        drop_table(event_table)
        drop_table(agreement_table)
