"""Shared ToolSource lookup-or-create helper.

A ``ToolSource`` row is content-addressable: the same persisted tool XML (or
JSON, for CWL) under the same parser class always corresponds to one row.
Both the async tool-request API and the workflow tool-step capture mint
ToolRequests that point at a ToolSource, and both can share the same row
when the tool/version is identical.

``ToolSource`` carries a ``UniqueConstraint("hash", "source_class")``, so
even under concurrent inserts (PostgreSQL) at most one row survives;
:func:`get_or_create_tool_source` retries on the unique-violation race to
return the winner.
"""

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from galaxy.model import ToolSource

log = logging.getLogger(__name__)


def get_or_create_tool_source(session, tool) -> ToolSource:
    """Return a ToolSource row matching the tool's persisted source content,
    creating one only when no equivalent row exists."""
    source_str = tool.tool_source.to_string()
    source_class = type(tool.tool_source).__name__
    content_hash = hashlib.sha256(source_str.encode("utf-8")).hexdigest()
    existing = _lookup(session, content_hash, source_class)
    if existing is not None:
        return existing
    tool_source = ToolSource(
        source=source_str,
        source_class=source_class,
        hash=content_hash,
    )
    session.add(tool_source)
    try:
        session.flush()
    except IntegrityError:
        # Concurrent writer won the race; roll back our insert and return
        # theirs. The unique constraint guarantees a row exists now.
        session.rollback()
        winner = _lookup(session, content_hash, source_class)
        if winner is None:
            raise
        return winner
    return tool_source


def _lookup(session, content_hash: str, source_class: str):
    return session.scalars(
        select(ToolSource)
        .where(ToolSource.hash == content_hash, ToolSource.source_class == source_class)
        .limit(1)
    ).first()
