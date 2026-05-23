from types import SimpleNamespace

from sqlalchemy import select

from galaxy import model
from galaxy.managers import tool_source as tool_source_module
from galaxy.managers.tool_source import (
    get_or_create_tool_source,
    tool_source_identity_hash,
)
from .base import BaseTestCase


class FakeToolSource:
    def __init__(self, body: str):
        self._body = body

    def to_string(self) -> str:
        return self._body


def _fake_tool(body: str = "<tool/>", tool_id: str = "tool1", version: str = "1.0", dynamic_tool=None):
    return SimpleNamespace(
        tool_source=FakeToolSource(body),
        id=tool_id,
        version=version,
        dynamic_tool=dynamic_tool,
    )


class TestToolSourceHelper(BaseTestCase):
    def test_returns_existing_row_on_second_call(self):
        session = self.trans.sa_session
        tool = _fake_tool(body="<tool id='t'/>")

        first = get_or_create_tool_source(session, tool)
        second = get_or_create_tool_source(session, tool)

        assert first.id == second.id

        rows = session.scalars(
            select(model.ToolSource).where(
                model.ToolSource.hash == first.hash,
                model.ToolSource.source_class == first.source_class,
                model.ToolSource.identity_hash == first.identity_hash,
            )
        ).all()
        assert len(rows) == 1

    def test_distinct_dynamic_tool_identity_creates_distinct_rows(self):
        session = self.trans.sa_session
        dynamic_tool_a = model.DynamicTool(tool_id="tool1", tool_version="1.0")
        dynamic_tool_b = model.DynamicTool(tool_id="tool1", tool_version="1.0")
        session.add_all([dynamic_tool_a, dynamic_tool_b])
        session.flush()

        a = get_or_create_tool_source(session, _fake_tool(dynamic_tool=dynamic_tool_a))
        b = get_or_create_tool_source(session, _fake_tool(dynamic_tool=dynamic_tool_b))

        assert a.id != b.id
        assert a.hash == b.hash
        assert a.source_class == b.source_class
        assert a.identity_hash != b.identity_hash
        assert a.dynamic_tool_id == dynamic_tool_a.id
        assert b.dynamic_tool_id == dynamic_tool_b.id

    def test_distinct_content_creates_distinct_rows(self):
        session = self.trans.sa_session
        a = get_or_create_tool_source(session, _fake_tool(body="<tool id='a'/>"))
        b = get_or_create_tool_source(session, _fake_tool(body="<tool id='b'/>"))
        assert a.id != b.id
        assert a.hash != b.hash

    def test_race_path_returns_winning_row(self):
        """When ``flush`` raises ``IntegrityError`` (concurrent inserter
        already won), the helper rolls back and returns the lookup winner."""
        from unittest.mock import patch

        from sqlalchemy.exc import IntegrityError

        session = self.trans.sa_session
        tool = _fake_tool(body="<tool id='race'/>")

        winner = model.ToolSource(
            hash="winner_hash",
            identity_hash=tool_source_identity_hash(tool),
            source="<tool/>",
            source_class="FakeToolSource",
        )

        lookup_calls = {"n": 0}

        def flaky_lookup(s, h, c, i):
            lookup_calls["n"] += 1
            if lookup_calls["n"] == 1:
                return None
            return winner

        def raise_integrity(*args, **kwargs):
            raise IntegrityError("simulated", params=None, orig=Exception("UNIQUE"))

        rolled_back = {"called": False}

        def record_rollback():
            rolled_back["called"] = True

        with (
            patch.object(tool_source_module, "_lookup", flaky_lookup),
            patch.object(session, "flush", raise_integrity),
            patch.object(session, "rollback", record_rollback),
        ):
            result = get_or_create_tool_source(session, tool)
        assert result is winner
        assert lookup_calls["n"] == 2
        assert rolled_back["called"] is True
