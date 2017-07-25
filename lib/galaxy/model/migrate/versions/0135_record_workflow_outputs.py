"""
Migration script for workflow request tables.
"""
from __future__ import print_function

import logging

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table

log = logging.getLogger( __name__ )
metadata = MetaData()


WorkflowInvocationToOutputDatasetAssociation_table = Table(
    "workflow_invocation_to_output_dataset_association", metadata,
    Column( "id", Integer, primary_key=True ),
    Column( "workflow_invocation_id", Integer, ForeignKey( "workflow_invocation.id" ), index=True ),
    Column( "workflow_step_id", Integer, ForeignKey("workflow_step.id") ),
    Column( "dataset_id", Integer, ForeignKey( "history_dataset_association.id" ), index=True ),
    Column( "workflow_output_id", Integer, ForeignKey("workflow_output.id") ),
)


WorkflowInvocationToOutputDatasetCollectionAssociation_table = Table(
    "workflow_invocation_to_output_dataset_collection_association", metadata,
    Column( "id", Integer, primary_key=True ),
    Column( "workflow_invocation_id", Integer, ForeignKey( "workflow_invocation.id" ), index=True ),
    Column( "workflow_step_id", Integer, ForeignKey("workflow_step.id") ),
    Column( "dataset_collection_id", Integer, ForeignKey( "history_dataset_collection_association.id" ), index=True ),
    Column( "workflow_output_id", Integer, ForeignKey("workflow_output.id") ),
)


WorkflowInvocationToImplicitOutputDatasetCollectionAssociation_table = Table(
    "workflow_invocation_to_implicit_output_dataset_collection_association", metadata,
    Column( "id", Integer, primary_key=True ),
    Column( "workflow_invocation_id", Integer, ForeignKey( "workflow_invocation.id" ), index=True ),
    Column( "workflow_step_id", Integer, ForeignKey("workflow_step.id") ),
    Column( "dataset_collection_id", Integer, ForeignKey( "dataset_collection.id" ), index=True ),
    Column( "workflow_output_id", Integer, ForeignKey("workflow_output.id") ),
)


TABLES = [
    WorkflowInvocationToOutputDatasetAssociation_table,
    WorkflowInvocationToOutputDatasetCollectionAssociation_table,
    WorkflowInvocationToImplicitOutputDatasetCollectionAssociation_table,
]


def upgrade(migrate_engine):
    metadata.bind = migrate_engine
    print(__doc__)
    metadata.reflect()

    for table in TABLES:
        __create(table)


def downgrade(migrate_engine):
    metadata.bind = migrate_engine
    metadata.reflect()

    for table in TABLES:
        __drop(table)


def __create(table):
    try:
        table.create()
    except Exception:
        log.exception("Creating %s table failed.", table.name)


def __drop(table):
    try:
        table.drop()
    except Exception:
        log.exception("Dropping %s table failed.", table.name)
