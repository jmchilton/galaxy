"""Refuse jobs of tools whose static security review, run at load on the patched source, keeps findings."""

import logging
import os
from typing import TYPE_CHECKING

from galaxy.exceptions import ConfigurationError
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import ToolPatchDatabase
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.charsets import SEVERITIES
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


def validate_static_findings_config(config: "GalaxyAppConfiguration") -> None:
    severity = config.tool_security_refuse_static_findings_severity
    if config.tool_security_refuse_static_findings and severity not in SEVERITIES:
        raise ConfigurationError(
            f"tool_security_refuse_static_findings_severity must be one of {', '.join(SEVERITIES)}, not '{severity}'"
        )


def expected_review_version(config: "GalaxyAppConfiguration", path: StrPath | None) -> str | None:
    """The version a current static review of the tool at ``path`` has; None when it is not reviewed."""
    if not config.tool_security_refuse_static_findings:
        return None
    if path is not None and in_directory(os.path.abspath(path), GALAXY_PACKAGE_DIR):
        return None
    return REVIEW_VERSION


def static_review_is_current(
    config: "GalaxyAppConfiguration", review: StaticReview | None, path: StrPath | None
) -> bool:
    return (review.version if review else None) == expected_review_version(config, path)


def with_static_review(config: "GalaxyAppConfiguration", tool_source: ToolSource, path: StrPath | None) -> ToolSource:
    """Review ``tool_source`` as loaded and keep the review on it when refusals are on; never raises."""
    version = expected_review_version(config, path)
    if version is None:
        tool_source.static_review = None
        return tool_source
    try:
        review = StaticReview.of(review_tool_source(tool_source), version)
        if rules := review.refused_rules(config.tool_security_refuse_static_findings_severity):
            log.info("Jobs of tool %s are refused, its static security review reports %s", path, ", ".join(rules))
    except Exception as e:
        log.warning("Static security review of tool %s failed, its jobs are not refused: %s", path, e)
        review = StaticReview(error=type(e).__name__, version=version)
    tool_source.static_review = review
    return tool_source


def patch_and_review_tool_source(
    config: "GalaxyAppConfiguration",
    db: ToolPatchDatabase | None,
    tool_source: ToolSource,
    guid: str | None,
    config_file: StrPath | None,
) -> ToolSource:
    """Patch a freshly parsed tool source, then review the patched source when refusals are on."""
    return with_static_review(config, apply_tool_patches(db, tool_source, guid, config_file), config_file)


def refused_rules(tool: "Tool", config: "GalaxyAppConfiguration") -> list[str]:
    """The rules of the tool's static review that refuse its jobs; empty when refusals are off."""
    if not config.tool_security_refuse_static_findings or tool.static_review is None:
        return []
    return tool.static_review.refused_rules(config.tool_security_refuse_static_findings_severity)


def check_static_findings(tool: "Tool", config: "GalaxyAppConfiguration") -> None:
    """Raise :class:`ToolInputRejected` for a job of a tool whose static review refuses it."""
    if rules := refused_rules(tool, config):
        raise ToolInputRejected(static_findings_message(tool, rules), [STATIC_FINDINGS])


def static_findings_message(tool: "Tool", rules: list[str]) -> str:
    # Galaxy keeps the first 255 characters of a job's info: the rules come before the tool's id.
    return (
        f"This job was not run: the security review of this tool reports {', '.join(rules)}, and this Galaxy server"
        f" does not run such tools. Please contact the administrators of this server. Tool '{tool.name}'"
        f" ({tool.id} version {tool.version})."
    )
