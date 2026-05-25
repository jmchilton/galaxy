"""Red-green tests for ``tool_for_execution`` resolution strategies.

Covers the matrix of (toolbox hit/miss) x (tool_source present/absent) x
(strategy "toolbox" / "rebuild"), the ``tool_execution_state=`` kwarg
shape, and the API guards (required strategy, mutual exclusion). The
rebuild path is exercised via a patch on
``create_tool_from_representation`` so we do not need a real ToolSource
blob.
"""

from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)

import pytest

from galaxy.exceptions import MessageException
from galaxy.managers.tool_execution import tool_for_execution


def _toolbox_returning(tool):
    toolbox = MagicMock()
    toolbox.get_tool.return_value = tool
    return toolbox


def _toolbox_missing():
    toolbox = MagicMock()
    toolbox.get_tool.return_value = None
    return toolbox


def _toolbox_raising():
    toolbox = MagicMock()
    toolbox.get_tool.side_effect = MessageException("nope")
    return toolbox


def _tool_source(
    *, source="<tool/>", source_class="XmlToolSource", tool_id="t.guid", tool_version=None, dynamic_tool=None
):
    return SimpleNamespace(
        source=source,
        source_class=source_class,
        tool_id=tool_id,
        tool_version=tool_version,
        dynamic_tool=dynamic_tool,
    )


def _tes(tool_source):
    return SimpleNamespace(tool_source=tool_source)


def test_toolbox_hit_no_source_returns_toolbox_tool():
    tool = SimpleNamespace(name="t")
    result = tool_for_execution(app=None, toolbox=_toolbox_returning(tool), strategy="toolbox", tool_id="t")
    assert result is tool


def test_toolbox_miss_no_source_returns_none():
    result = tool_for_execution(app=None, toolbox=_toolbox_missing(), strategy="toolbox", tool_id="t")
    assert result is None


def test_toolbox_message_exception_returns_none():
    result = tool_for_execution(app=None, toolbox=_toolbox_raising(), strategy="toolbox", tool_id="t")
    assert result is None


def test_toolbox_miss_source_supplied_rebuilds_via_model():
    app = MagicMock()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt) as factory:
        result = tool_for_execution(app=app, toolbox=_toolbox_missing(), strategy="rebuild", tool_source=_tool_source())
    assert result is rebuilt
    factory.assert_called_once()


def test_rebuild_strategy_skips_toolbox_when_source_present():
    app = MagicMock()
    toolbox_tool = SimpleNamespace(name="from_toolbox")
    rebuilt = SimpleNamespace(dynamic_tool=None)
    toolbox = _toolbox_returning(toolbox_tool)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        result = tool_for_execution(app=app, toolbox=toolbox, strategy="rebuild", tool_source=_tool_source())
    assert result is rebuilt
    toolbox.get_tool.assert_not_called()


def test_toolbox_strategy_prefers_toolbox_over_source():
    app = MagicMock()
    toolbox_tool = SimpleNamespace(name="from_toolbox")
    with patch("galaxy.managers.tool_execution.create_tool_from_representation") as factory:
        result = tool_for_execution(
            app=app,
            toolbox=_toolbox_returning(toolbox_tool),
            strategy="toolbox",
            tool_id="t",
            tool_source=_tool_source(),
        )
    assert result is toolbox_tool
    factory.assert_not_called()


def test_toolbox_miss_source_supplied_strategy_toolbox_falls_back_to_rebuild():
    app = MagicMock()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        result = tool_for_execution(
            app=app,
            toolbox=_toolbox_missing(),
            strategy="toolbox",
            tool_id="t",
            tool_source=_tool_source(),
        )
    assert result is rebuilt


def test_rebuild_attaches_source_dynamic_tool():
    app = MagicMock()
    source_dyn = object()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        tool_for_execution(app=app, toolbox=None, strategy="rebuild", tool_source=_tool_source(dynamic_tool=source_dyn))
    assert rebuilt.dynamic_tool is source_dyn


def test_rebuild_explicit_dynamic_tool_wins():
    app = MagicMock()
    explicit_dyn = object()
    source_dyn = object()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        tool_for_execution(
            app=app,
            toolbox=None,
            strategy="rebuild",
            tool_source=_tool_source(dynamic_tool=source_dyn),
            dynamic_tool=explicit_dyn,
        )
    assert rebuilt.dynamic_tool is explicit_dyn


def test_no_tool_id_and_no_source_returns_none():
    assert tool_for_execution(app=None, toolbox=_toolbox_returning(object()), strategy="toolbox") is None


def test_tool_execution_state_kwarg_derives_identity_for_toolbox_strategy():
    # TES-supplied identity must flow through to the toolbox lookup so the
    # consumer can pass `tool_execution_state=` symmetrically regardless of
    # which strategy is chosen.
    tool = SimpleNamespace(name="t")
    toolbox = _toolbox_returning(tool)
    tes = _tes(_tool_source(tool_id="some.tool", source=None, source_class=None))
    result = tool_for_execution(app=None, toolbox=toolbox, strategy="toolbox", tool_execution_state=tes)
    assert result is tool
    toolbox.get_tool.assert_called_once_with("some.tool", tool_version=None)


def test_tool_execution_state_kwarg_derives_identity_for_rebuild_strategy():
    app = MagicMock()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    source_dyn = object()
    tes = _tes(_tool_source(dynamic_tool=source_dyn))
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt) as factory:
        result = tool_for_execution(app=app, toolbox=None, strategy="rebuild", tool_execution_state=tes)
    assert result is rebuilt
    assert rebuilt.dynamic_tool is source_dyn
    factory.assert_called_once()


def test_strategy_is_required():
    # Strategy carries load-bearing semantics (live registry vs persisted
    # source); the call must declare it rather than infer.
    with pytest.raises(TypeError):
        tool_for_execution(app=None, toolbox=_toolbox_missing(), tool_id="t")  # type: ignore[call-arg]


def test_tool_execution_state_mutually_exclusive_with_primitives():
    tes = _tes(_tool_source())
    with pytest.raises(TypeError, match="mutually exclusive"):
        tool_for_execution(
            app=None,
            toolbox=None,
            strategy="rebuild",
            tool_execution_state=tes,
            tool_id="t",
        )
