import pytest

from galaxy.tool_util.security.classify import NOT_CHECKABLE
from galaxy.tool_util.security.refusal import StaticReview
from galaxy.tool_util.security.report import (
    CAPABILITY,
    Finding,
    NOT_ANALYSED,
    Report,
    VULNERABILITY,
)


def _finding(rule: str, severity: str, kind: str = VULNERABILITY, location: str = "command") -> Finding:
    return Finding(rule=rule, kind=kind, severity=severity, message="m", location=location)


def _review(*findings: Finding) -> StaticReview:
    return StaticReview.of(Report(findings=list(findings)), version="1")


def test_keeps_the_worst_severity_of_each_rule() -> None:
    review = _review(
        _finding("shell-injection", "medium"),
        _finding("shell-injection", "high", location="configfile:script"),
        _finding("shell-injection", "low", location="configfile:other"),
        _finding("template-exec", "critical", kind=CAPABILITY),
    )
    assert review.severities == {"shell-injection": "high", "template-exec": "critical"}


@pytest.mark.parametrize(
    "threshold, refused",
    [
        ("critical", ["template-exec"]),
        ("high", ["shell-injection", "template-exec"]),
        ("medium", ["argument-injection", "shell-injection", "template-exec"]),
    ],
)
def test_refuses_rules_at_or_above_the_threshold(threshold: str, refused: list[str]) -> None:
    review = _review(
        _finding("template-exec", "critical", kind=CAPABILITY),
        _finding("shell-injection", "high"),
        _finding("argument-injection", "medium"),
        _finding("capability-container", "info", kind=CAPABILITY),
    )
    assert review.refused_rules(threshold) == refused


def test_uncheckable_codes_and_unchecked_locations_alone_refuse_nothing() -> None:
    report = Report(
        unanalyzed=["command: $x is not a tool input, its value was not followed"],
        unchecked_locations={"command": NOT_ANALYSED, "configfile:script": NOT_CHECKABLE},
        rewrites={"command": ["decode"]},
    )
    assert StaticReview.of(report, version="1").refused_rules("low") == []
