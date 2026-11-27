"""What the tool security reviews share: how they refuse a job, and which tools they leave alone.

A review refuses a job by raising :class:`ToolInputRejected` while the job is prepared. Every job
runner then fails the job at once and never resubmits it, since another destination would refuse it
too (:data:`galaxy.jobs.runners.PREPARE_REFUSALS`). No review reviews Galaxy's own tools, interactive
tools or CWL tools (:func:`review_exclusion`).
"""

import os
from collections.abc import Iterable
from typing import TYPE_CHECKING

from galaxy.tool_util.parser.cwl import CwlToolSource
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tools.special_tools import hidden_lib_tool_paths
from galaxy.util.path import StrPath

if TYPE_CHECKING:
    from galaxy.tools import Tool

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
# Galaxy's own upload tool, wherever Galaxy is installed: a source checkout links bundled to tools/.
_GALAXY_UPLOAD_TOOL = os.path.realpath(os.path.join(_TOOLS_DIR, "bundled", "data_source", "upload.xml"))
_UPLOAD_ACTION = ("galaxy.tools.actions.upload", "UploadToolAction")


def _real_lib_path(path: str, tools_dir: str) -> str:
    # Resolved from the real path of tools_dir: where the packages link galaxy/tools to lib/galaxy/tools,
    # set metadata's ../datatypes exists only beside the real directory.
    return os.path.realpath(os.path.join(os.path.realpath(tools_dir), os.path.relpath(path, tools_dir)))


# The upload tool, and the tools Galaxy runs as its own machinery: set metadata, data fetch, history import and export.
_GALAXY_OWN_TOOLS = frozenset(
    (_GALAXY_UPLOAD_TOOL, *(_real_lib_path(path, _TOOLS_DIR) for path in hidden_lib_tool_paths()))
)


# The tool types the reviews leave out (the type of the class Galaxy builds a tool as), and why.
_EXCLUDED_TOOL_TYPES = {
    # It is meant to run in its own container, may get the user's API key by design, and an administrator
    # enables interactive tools explicitly.
    "interactive": "it is an interactive tool",
    # Its command line is built from its CWL description: there is no Cheetah command template to review.
    "cwl": "it is a CWL tool",
}
CWL_TOOL_TYPE = "cwl"
GALAXY_OWN_TOOL = "it is one of Galaxy's own tools"


class ToolInputRejected(Exception):
    """A tool security review refuses a job while it is prepared; ``codes`` name why."""

    def __init__(self, message: str, codes: Iterable[str] = ()) -> None:
        # Galaxy keeps the first 255 characters of a job's info: the codes come first.
        self.codes = tuple(sorted(set(codes)))
        super().__init__(f"[{', '.join(self.codes)}] {message}" if self.codes else message)


def is_galaxy_own_tool(path: StrPath | None, *, patched: bool = False) -> bool:
    """True when the tool at ``path`` is one of Galaxy's own tools, which the tool security reviews do not review.

    These are Galaxy's upload tool (:func:`is_galaxy_upload_tool`) and the tools Galaxy runs as its own
    machinery: set metadata, data fetch, and history import and export
    (:func:`galaxy.tools.special_tools.hidden_lib_tool_paths`). Each matches by its real path only, so a
    copy elsewhere is reviewed. Every other tool Galaxy ships is reviewed: stock tools in every install
    layout, converters, collection operations and sample sheet tools. A tool a tool patch applies to
    (``patched``) is no longer the tool Galaxy ships, and is reviewed too.
    """
    return not patched and path is not None and os.path.realpath(path) in _GALAXY_OWN_TOOLS


def review_exclusion(path: StrPath | None, tool_type: str | None, *, patched: bool = False) -> str | None:
    """Why the tool security reviews leave out the tool at ``path``, or None when they review it.

    They leave out Galaxy's own tools (:func:`is_galaxy_own_tool`, which takes ``patched``), interactive
    tools and CWL tools. ``tool_type`` is the type of the class Galaxy builds the tool as: ``Tool.tool_type``
    of a loaded tool, or :func:`built_tool_type` of its source. Galaxy builds an ``InteractiveTool`` only
    when an administrator enables interactive tools (``interactivetools_enable``); such a tool is meant to
    run in its own container and may get the user's API key by design. Entry points alone do not make a
    tool interactive, and a ``tool_type="interactive"`` that a ``<type>`` element overrides does not
    either. A CWL tool has no Cheetah command template. The static review
    (``python -m galaxy.tool_util.security``) still reports the findings of the tools left out.
    """
    if is_galaxy_own_tool(path, patched=patched):
        return GALAXY_OWN_TOOL
    return _EXCLUDED_TOOL_TYPES.get(tool_type or "")


def built_tool_type(tool_source: ToolSource) -> str | None:
    """The ``tool_type`` of the class Galaxy builds ``tool_source`` as, as :func:`review_exclusion` takes it.

    The class is :func:`galaxy.tools.tool_class_for_source`'s, so a ``<type>`` element wins over a declared
    ``tool_type``, and entry points alone make no tool interactive. A CWL tool source gives ``cwl``, though
    Galaxy does not build CWL tools yet. None when Galaxy cannot build the tool: it does not load, and
    nothing is left out.
    """
    if isinstance(tool_source, CwlToolSource):
        return CWL_TOOL_TYPE
    from galaxy.tools import tool_class_for_source

    try:
        tool_type: str = tool_class_for_source(tool_source).tool_type
    except Exception:
        return None
    return tool_type


def is_galaxy_upload_tool(path: StrPath | None) -> bool:
    """True when the tool at ``path`` is Galaxy's own upload tool (``upload1``).

    Galaxy gives the tool its outputs when it creates the job, so its template can only read them by a
    computed name: reflection the review cannot check. Only a tool file at Galaxy's bundled path, or a
    link to it, matches; a copy elsewhere with the same id or action does not. Galaxy's job code tells
    the upload tool by its id: this is stricter on purpose.
    """
    return path is not None and os.path.realpath(path) == _GALAXY_UPLOAD_TOOL


def declares_upload_tool(tool_source: ToolSource) -> bool:
    """True when ``tool_source`` declares the id and action of Galaxy's upload tool, from whatever path."""
    declared: bool = tool_source.parse_id() == "upload1" and tool_source.parse_action_module() == _UPLOAD_ACTION
    return declared


def upload_tool_lookalike_message(path: StrPath | None) -> str:
    """Why a tool that declares Galaxy's upload tool from another path is reviewed."""
    return (
        f"Tool upload1 at {path} declares Galaxy's upload tool but is not Galaxy's own {_GALAXY_UPLOAD_TOOL}:"
        " it is reviewed like any other tool, and the review may refuse its jobs"
    )


def tool_file(tool: "Tool") -> StrPath | None:
    """The file the tool was loaded from, also when the cached toolbox built it from its store."""
    path: StrPath | None = tool.config_file or tool.stored_source_path
    return path
