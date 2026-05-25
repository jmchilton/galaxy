"""Resolve a Tool from execution-time identity.

A captured tool execution carries some subset of {``tool_id``,
``tool_version``, ``DynamicTool``, persisted ``ToolSource``}. Two
strategies turn that identity into a Tool object: a toolbox lookup
(authoritative when the tool is currently registered) and a rebuild
from the persisted ``ToolSource`` blob (authoritative for
ToolRequest-sourced executions, including jobless ones). Consumers
(History Graph display names, workflow extraction step rebuild) used
to roll their own; this module unifies them.

Callers either pass a ``ToolExecutionState`` (preferred -- the TES
carries every primitive symmetrically via ``tool_source``) or the
identity primitives directly. The strategy is always explicit: it
encodes which source is authoritative for the consumer (live registry
vs persisted blob), which the input shape can no longer disambiguate.

The rebuild here is uncached. ``galaxy.celery.tasks`` keeps a
worker-local ``cached_create_tool_from_representation`` for the
queue_jobs / finish_job hot paths; collapsing the two cache homes into
one is a documented follow-up, gated on the dict-vs-str cache-key
question for in-process callers (extract.py passes the JSONType dict;
celery callers pass a serialized string).
"""

import logging
from typing import (
    Literal,
    Optional,
    TYPE_CHECKING,
)

from galaxy.exceptions import MessageException
from galaxy.tools import create_tool_from_representation

if TYPE_CHECKING:
    from galaxy.model import (
        DynamicTool,
        ToolExecutionState,
        ToolSource as ToolSourceModel,
    )
    from galaxy.structured_app import MinimalManagerApp
    from galaxy.tool_util.toolbox import AbstractToolBox
    from galaxy.tools import Tool

log = logging.getLogger(__name__)

ResolutionStrategy = Literal["toolbox", "rebuild"]


def tool_for_execution(
    app: Optional["MinimalManagerApp"],
    toolbox: Optional["AbstractToolBox"],
    *,
    strategy: ResolutionStrategy,
    tool_execution_state: Optional["ToolExecutionState"] = None,
    tool_id: Optional[str] = None,
    tool_version: Optional[str] = None,
    dynamic_tool: Optional["DynamicTool"] = None,
    tool_source: Optional["ToolSourceModel"] = None,
) -> Optional["Tool"]:
    """Resolve a Tool for a captured execution event.

    ``strategy`` is required; ``"toolbox"`` consults the live registry
    first (with persisted-source rebuild as fallback when present),
    ``"rebuild"`` reconstructs from the persisted ``ToolSource`` first
    (with toolbox fallback). Pass ``tool_execution_state=`` to derive
    every identity primitive from ``tes.tool_source`` symmetrically,
    or pass the primitives directly -- the two shapes are mutually
    exclusive. Returns ``None`` when no strategy produces a tool;
    toolbox ``MessageException`` is swallowed to a ``None`` result so
    display-time callers do not need their own try/except. ``app`` may
    be ``None`` for callers that only need the toolbox path (History
    Graph); rebuild paths require it.
    """
    if tool_execution_state is not None:
        primitives = (tool_id, tool_version, dynamic_tool, tool_source)
        if any(p is not None for p in primitives):
            raise TypeError("tool_execution_state= is mutually exclusive with identity primitives")
        ts = tool_execution_state.tool_source
        tool_id = ts.tool_id
        tool_version = ts.tool_version
        dynamic_tool = ts.dynamic_tool
        tool_source = ts

    if strategy == "toolbox":
        tool = _toolbox_lookup(toolbox, tool_id=tool_id, tool_version=tool_version)
        if tool is None and tool_source is not None:
            tool = _rebuild_from_source(app, tool_source=tool_source, dynamic_tool=dynamic_tool)
        return tool

    tool = (
        _rebuild_from_source(app, tool_source=tool_source, dynamic_tool=dynamic_tool)
        if tool_source is not None
        else None
    )
    if tool is None:
        tool = _toolbox_lookup(toolbox, tool_id=tool_id, tool_version=tool_version)
    return tool


def _toolbox_lookup(
    toolbox: Optional["AbstractToolBox"],
    *,
    tool_id: Optional[str],
    tool_version: Optional[str],
) -> Optional["Tool"]:
    if toolbox is None or not tool_id:
        return None
    try:
        return toolbox.get_tool(tool_id, tool_version=tool_version)
    except MessageException:
        return None


def _rebuild_from_source(
    app: Optional["MinimalManagerApp"],
    *,
    tool_source: "ToolSourceModel",
    dynamic_tool: Optional["DynamicTool"],
) -> "Tool":
    """Rebuild a Tool from the persisted ToolSource. ``tool_dir`` is
    runtime-only and unavailable here, so tool_dir-dependent
    reconstruction edges remain a documented limitation (parity with
    the celery worker path). The DynamicTool argument wins if supplied,
    else falls back to the source's own link.
    """
    assert app is not None, "tool_for_execution(): rebuild from persisted source requires an app"
    tool = create_tool_from_representation(
        app,
        tool_source.source,
        tool_dir=None,
        tool_source_class=tool_source.source_class,
        guid=tool_source.tool_id,
    )
    attached = dynamic_tool if dynamic_tool is not None else tool_source.dynamic_tool
    if attached is not None:
        tool.dynamic_tool = attached
    return tool
