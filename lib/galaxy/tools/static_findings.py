"""Refuse jobs of tools whose static security review, run at load on the patched source, keeps findings."""

import logging
import os
from typing import TYPE_CHECKING

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import ToolPatchDatabase
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.refusal import (
    STATIC_FINDINGS,
    StaticReview,
)
from galaxy.tools.patches import apply_tool_patches
from galaxy.tools.security_refusal import ToolInputRejected
from galaxy.util import in_directory
from galaxy.util.path import StrPath
from galaxy.version import VERSION

if TYPE_CHECKING:
    from galaxy.config import GalaxyAppConfiguration
    from galaxy.tools import Tool

log = logging.getLogger(__name__)

# Galaxy's own tools (set metadata, data fetch, collection operations) are part of Galaxy and not reviewed.
GALAXY_PACKAGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# A stored review from another Galaxy version is redone: the analyser may have changed.
REVIEW_VERSION: str = VERSION


def reviews_tool(config: "GalaxyAppConfiguration", path: StrPath | None) -> bool:
    """True when refusals are on and the tool at ``path`` is not one of Galaxy's own."""
    if not config.tool_security_refuse_static_findings:
        return False
    return path is None or not in_directory(os.path.abspath(path), GALAXY_PACKAGE_DIR)


def static_review_is_current(
    config: "GalaxyAppConfiguration", review: StaticReview | None, path: StrPath | None
) -> bool:
    """True when ``review`` is what :func:`with_static_review` would keep on the tool at ``path`` now."""
    if not reviews_tool(config, path):
        return review is None
    return review is not None and review.version == REVIEW_VERSION


def with_static_review(
    config: "GalaxyAppConfiguration", tool_source: ToolSource, path: StrPath | None, kept: StaticReview | None = None
) -> ToolSource:
    """Keep a review on ``tool_source`` when refusals are on: ``kept`` if current, else a new one; never raises."""
    if not reviews_tool(config, path):
        tool_source.static_review = None
    elif kept is not None and kept.version == REVIEW_VERSION:
        tool_source.static_review = kept
    else:
        tool_source.static_review = _review(config, tool_source, path)
    return tool_source


def _review(config: "GalaxyAppConfiguration", tool_source: ToolSource, path: StrPath | None) -> StaticReview:
    try:
        review = StaticReview.of(review_tool_source(tool_source), REVIEW_VERSION)
        if rules := review.refused_rules(config.tool_security_refuse_static_findings_severity):
            log.info("Jobs of tool %s are refused, its static security review reports %s", path, ", ".join(rules))
        return review
    except Exception as e:
        log.warning("Static security review of tool %s failed, its jobs are not refused: %s", path, e)
        return StaticReview(error=type(e).__name__, version=REVIEW_VERSION)


def patch_and_review_tool_source(
    config: "GalaxyAppConfiguration",
    db: ToolPatchDatabase | None,
    tool_source: ToolSource,
    guid: str | None,
    config_file: StrPath | None,
) -> ToolSource:
    """Patch a freshly parsed tool source, then review the patched source when refusals are on."""
    return with_static_review(config, apply_tool_patches(db, tool_source, guid, config_file), config_file)


def check_static_findings(tool: "Tool", config: "GalaxyAppConfiguration") -> None:
    """Raise :class:`ToolInputRejected` for a job of a tool whose static review refuses it."""
    if not config.tool_security_refuse_static_findings or tool.static_review is None:
        return
    if rules := tool.static_review.refused_rules(config.tool_security_refuse_static_findings_severity):
        # Galaxy keeps the first 255 characters of a job's info: the rules come before the tool's id.
        raise ToolInputRejected(
            f"This job was not run: the security review of this tool reports {', '.join(rules)}, and this Galaxy"
            " server does not run such tools. Please contact the administrators of this server. Tool"
            f" '{tool.name}' ({tool.id} version {tool.version}).",
            [STATIC_FINDINGS],
        )
