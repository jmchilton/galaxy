"""Red-green tests for ``tool_for_execution`` resolution strategies.

Covers the matrix of (toolbox hit/miss) x (tool_source present/absent) x
(prefer=None / "toolbox" / "model"). The model rebuild path is exercised
via a patch on ``create_tool_from_representation`` so we do not need a
real ToolSource blob.
"""

from types import SimpleNamespace
from unittest.mock import (
    MagicMock,
    patch,
)

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


def _tool_source(*, source="<tool/>", source_class="XmlToolSource", tool_id="t.guid", dynamic_tool=None):
    return SimpleNamespace(source=source, source_class=source_class, tool_id=tool_id, dynamic_tool=dynamic_tool)


def test_toolbox_hit_no_source_returns_toolbox_tool():
    tool = SimpleNamespace(name="t")
    result = tool_for_execution(app=None, toolbox=_toolbox_returning(tool), tool_id="t")
    assert result is tool


def test_toolbox_miss_no_source_returns_none():
    result = tool_for_execution(app=None, toolbox=_toolbox_missing(), tool_id="t")
    assert result is None


def test_toolbox_message_exception_returns_none():
    result = tool_for_execution(app=None, toolbox=_toolbox_raising(), tool_id="t")
    assert result is None


def test_toolbox_miss_source_supplied_rebuilds_via_model():
    app = MagicMock()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt) as factory:
        result = tool_for_execution(app=app, toolbox=_toolbox_missing(), tool_source=_tool_source())
    assert result is rebuilt
    factory.assert_called_once()


def test_toolbox_hit_source_supplied_prefer_none_picks_model():
    app = MagicMock()
    toolbox_tool = SimpleNamespace(name="from_toolbox")
    rebuilt = SimpleNamespace(dynamic_tool=None)
    toolbox = _toolbox_returning(toolbox_tool)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        result = tool_for_execution(app=app, toolbox=toolbox, tool_source=_tool_source())
    assert result is rebuilt
    toolbox.get_tool.assert_not_called()


def test_toolbox_hit_source_supplied_prefer_toolbox_picks_toolbox():
    app = MagicMock()
    toolbox_tool = SimpleNamespace(name="from_toolbox")
    with patch("galaxy.managers.tool_execution.create_tool_from_representation") as factory:
        result = tool_for_execution(
            app=app,
            toolbox=_toolbox_returning(toolbox_tool),
            tool_id="t",
            tool_source=_tool_source(),
            prefer="toolbox",
        )
    assert result is toolbox_tool
    factory.assert_not_called()


def test_toolbox_miss_source_supplied_prefer_toolbox_falls_back_to_model():
    app = MagicMock()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        result = tool_for_execution(
            app=app,
            toolbox=_toolbox_missing(),
            tool_id="t",
            tool_source=_tool_source(),
            prefer="toolbox",
        )
    assert result is rebuilt


def test_model_rebuild_attaches_source_dynamic_tool():
    app = MagicMock()
    source_dyn = object()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        tool_for_execution(app=app, toolbox=None, tool_source=_tool_source(dynamic_tool=source_dyn))
    assert rebuilt.dynamic_tool is source_dyn


def test_model_rebuild_explicit_dynamic_tool_wins():
    app = MagicMock()
    explicit_dyn = object()
    source_dyn = object()
    rebuilt = SimpleNamespace(dynamic_tool=None)
    with patch("galaxy.managers.tool_execution.create_tool_from_representation", return_value=rebuilt):
        tool_for_execution(
            app=app,
            toolbox=None,
            tool_source=_tool_source(dynamic_tool=source_dyn),
            dynamic_tool=explicit_dyn,
        )
    assert rebuilt.dynamic_tool is explicit_dyn


def test_no_tool_id_and_no_source_returns_none():
    assert tool_for_execution(app=None, toolbox=_toolbox_returning(object())) is None
