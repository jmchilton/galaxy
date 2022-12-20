"""
Migration script to add tool-centric tables
"""

from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    TEXT,
)

metadata = MetaData()

Tool_table = Table(
    "tool",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("repository_id", Integer, ForeignKey("repository.id"), index=True),
    Column("guid", TEXT),
)


RepositoryToolVersion_table = Table(
    "repository_tool_version",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("tool_id", Integer, ForeignKey("tool.id"), index=True),
    Column("repository_metadata_id", Integer, ForeignKey("repository_metadata.id"), index=True),
    Column("tool_version", TEXT),
)


def upgrade(migrate_engine):
    metadata.bind = migrate_engine
    print(__doc__)
    metadata.reflect()

    # Create new tables.
    try:
        Tool_table.create()
    except Exception:
        print("Creating tool table failed.")
    try:
        RepositoryToolVersion_table.create()
    except Exception:
        print("Dropping repository tool version table failed.")


def downgrade(migrate_engine):
    metadata.bind = migrate_engine
    metadata.reflect()

    try:
        RepositoryToolVersion_table.drop()
    except Exception:
        print("Dropping repository tool version table failed.")
    try:
        Tool_table.drop()
    except Exception:
        print("Dropping tool table failed.")
