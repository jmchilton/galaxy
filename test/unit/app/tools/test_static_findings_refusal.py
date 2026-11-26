import os
from dataclasses import dataclass
from pathlib import Path
from typing import (
    cast,
    TYPE_CHECKING,
)

import pytest

from galaxy.exceptions import ConfigurationError
from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.patches import load_tool_patch_database
from galaxy.tool_util.security.refusal import StaticReview
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tool_util.unittest_utils.tool_patches import (
    security_patch,
    write_collection,
)
from galaxy.tools import static_findings
from galaxy.tools.security_refusal import ToolInputRejected
from galaxy.tools.static_findings import (
    check_static_findings,
    GALAXY_PACKAGE_DIR,
    patch_and_review_tool_source,
    REVIEW_VERSION,
    static_review_is_current,
    validate_static_findings_config,
    with_static_review,
)

if TYPE_CHECKING:
    from galaxy.config import GalaxyAppConfiguration
    from galaxy.tools import Tool

TOOL = functional_test_tool_path("identifier_single.xml")
SET_METADATA_TOOL = os.path.join(GALAXY_PACKAGE_DIR, "datatypes", "set_metadata_tool.xml")
# nested-interpreter is high while the sanitizer lets `;` through, medium once the patch takes it out.
AWK_TOOL = """<tool id="static_lowered" name="static_lowered" version="1.0">
    <command><![CDATA[awk 'BEGIN { print $x }' > '$out']]></command>
    <inputs>
        <param name="x" type="text" value="a">
            <sanitizer invalid_char=""><valid initial="string.letters"><add value=";"/></valid></sanitizer>
        </param>
    </inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""
LOWERING = security_patch(
    [
        {
            "replace_element": {
                "path": "inputs/param[@name='x']/sanitizer/valid/add",
                "old": '<add value=";"/>',
                "new": '<add value="/"/>',
                "occurrences": 1,
            }
        }
    ],
    "ordinary_inputs",
    "Jobs whose value of x held ';' now run without it.",
)


@dataclass
class RefusalConfig:
    tool_security_refuse_static_findings: bool = True
    tool_security_refuse_static_findings_severity: str = "high"


@dataclass
class ReviewedTool:
    static_review: StaticReview
    name: str = "Cat"
    id: str = "cat1"
    version: str = "1.0"


def _config(refuse: bool = True, severity: str = "high") -> "GalaxyAppConfiguration":
    return cast("GalaxyAppConfiguration", RefusalConfig(refuse, severity))


def _tool(severities: dict[str, str]) -> "Tool":
    return cast("Tool", ReviewedTool(StaticReview(severities=severities, version=REVIEW_VERSION)))


def test_refuses_a_job_naming_the_rules_at_or_above_the_severity() -> None:
    tool = _tool({"argument-injection": "medium", "shell-injection": "high", "template-exec": "critical"})
    with pytest.raises(ToolInputRejected) as e:
        check_static_findings(tool, _config())
    assert str(e.value) == (
        "[static-findings] This job was not run: the security review of this tool reports shell-injection,"
        " template-exec, and this Galaxy server does not run such tools. Please contact the administrators of this"
        " server. Tool 'Cat' (cat1 version 1.0)."
    )


@pytest.mark.parametrize("refuse, severity", [(False, "high"), (True, "critical")], ids=["off", "below"])
def test_runs_a_job_without_a_finding_that_refuses(refuse: bool, severity: str) -> None:
    check_static_findings(_tool({"shell-injection": "high"}), _config(refuse, severity))


def test_reviews_the_patched_source_only_when_refusals_are_on(tmp_path: Path) -> None:
    tool = tmp_path / "static_lowered.xml"
    tool.write_text(AWK_TOOL)
    db = load_tool_patch_database([str(write_collection(tmp_path / "c", {"_local/static_lowered/1.0.yml": LOWERING}))])

    def review(config: "GalaxyAppConfiguration") -> StaticReview | None:
        return patch_and_review_tool_source(config, db, get_tool_source(str(tool)), None, tool).static_review

    assert review(_config()) == StaticReview(severities={"nested-interpreter": "medium"}, version=REVIEW_VERSION)
    assert review(_config(refuse=False)) is None


def test_galaxy_own_tools_are_not_reviewed() -> None:
    assert with_static_review(_config(), get_tool_source(SET_METADATA_TOOL), SET_METADATA_TOOL).static_review is None
    assert static_review_is_current(_config(), None, SET_METADATA_TOOL)


def test_failed_review_is_kept_and_refuses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(tool_source):
        raise RecursionError()

    monkeypatch.setattr(static_findings, "review_tool_source", fail)
    review = with_static_review(_config(), get_tool_source(TOOL), TOOL).static_review
    assert review == StaticReview(error="RecursionError", version=REVIEW_VERSION)
    assert review.refused_rules("low") == []


def test_unknown_severity_is_a_configuration_error() -> None:
    validate_static_findings_config(_config(refuse=False, severity="High"))
    with pytest.raises(ConfigurationError, match="not 'High'"):
        validate_static_findings_config(_config(severity="High"))
