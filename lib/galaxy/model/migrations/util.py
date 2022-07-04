import logging
from typing import List

from alembic import op
from sqlalchemy import inspect

log = logging.getLogger(__name__)


def drop_column(table_name, column_name):
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.drop_column(column_name)


def add_unique_constraint(index_name: str, table_name: str, columns: List[str]):
    bind = op.get_context().bind
    if bind.engine.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.create_unique_constraint(index_name, columns)
    else:
        op.create_unique_constraint(index_name, table_name, columns)


def drop_unique_constraint(index_name: str, table_name: str):
    bind = op.get_context().bind
    if bind.engine.name == "sqlite":
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.drop_constraint(index_name)
    else:
        op.drop_constraint(index_name, table_name)


def column_exists(table_name, column_name):
    bind = op.get_context().bind
    insp = inspect(bind)
    columns = insp.get_columns(table_name)
    return any(c["name"] == column_name for c in columns)
