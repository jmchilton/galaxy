import os
from types import SimpleNamespace

import pytest

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security.refusal import StaticReview
from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tools import static_findings
from galaxy.tools.security_refusal import ToolInputRejected
from galaxy.tools.static_findings import (
    check_static_findings,
    GALAXY_PACKAGE_DIR,
    REVIEW_VERSION,
    static_review_is_current,
    with_static_review,
)

TOOL = functional_test_tool_path("identifier_single.xml")
SET_METADATA_TOOL = os.path.join(GALAXY_PACKAGE_DIR, "datatypes", "set_metadata_tool.xml")


def _config(refuse: bool = True, severity: str = "high") -> SimpleNamespace:
    return SimpleNamespace(
        tool_security_refuse_static_findings=refuse, tool_security_refuse_static_findings_severity=severity
    )


def _tool(severities: dict[str, str]) -> SimpleNamespace:
    review = StaticReview(severities=severities, version=REVIEW_VERSION)
    return SimpleNamespace(static_review=review, name="Cat", id="cat1", version="1.0")


def test_refuses_a_job_naming_the_rules_at_or_above_the_severity() -> None:
    tool = _tool({"argument-injection": "medium", "shell-injection": "high", "template-exec": "critical"})
    with pytest.raises(ToolInputRejected) as e:
        check_static_findings(tool, _config())
    assert str(e.value) == (
        "[static-findings] This job was not run: the security review of this tool reports shell-injection,"
        " template-exec, and this Galaxy server does not run such tools. Please contact the administrators of this"
        " server. Tool 'Cat' (cat1 version 1.0)."
    )


@pytest.mark.parametrize("config", [_config(refuse=False), _config(severity="critical")], ids=["off", "below"])
def test_runs_a_job_without_a_finding_that_refuses(config: SimpleNamespace) -> None:
    check_static_findings(_tool({"shell-injection": "high"}), config)


def test_reviews_the_loaded_source_only_when_refusals_are_on() -> None:
    reviewed = with_static_review(_config(), get_tool_source(TOOL), TOOL)
    assert reviewed.static_review is not None
    assert reviewed.static_review.refused_rules("high") == ["shell-injection"]
    assert with_static_review(_config(refuse=False), get_tool_source(TOOL), TOOL).static_review is None


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
