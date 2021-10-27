"""
Migration script to support deferred dataset use cases.
"""

import logging

from sqlalchemy import (
    Boolean,
    Column,
    MetaData,
)

from galaxy.model.migrate.versions.util import (
    add_column,
    drop_column,
)

log = logging.getLogger(__name__)
metadata = MetaData()


def upgrade(migrate_engine):
    print(__doc__)
    metadata.bind = migrate_engine
    metadata.reflect()

    hda_metadata_deferred = Column("metadata_deferred", Boolean, default=False)
    add_column(hda_metadata_deferred, 'history_dataset_association', metadata)
    ldda_metadata_deferred = Column("metadata_deferred", Boolean, default=False)
    add_column(ldda_metadata_deferred, 'library_dataset_dataset_association', metadata)


def downgrade(migrate_engine):
    metadata.bind = migrate_engine
    metadata.reflect()

    drop_column('metadata_deferred', 'history_dataset_association', metadata)
    drop_column('metadata_deferred', 'library_dataset_dataset_association', metadata)
