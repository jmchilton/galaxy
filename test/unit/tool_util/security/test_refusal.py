from pathlib import Path

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
from .test_patch_review import _awk_review


def _finding(rule: str, severity: str, kind: str = VULNERABILITY, location: str = "command") -> Finding:
    return Finding(rule=rule, kind=kind, severity=severity, message="m", location=location)


def _review(*findings: Finding, **report: dict) -> StaticReview:
    return StaticReview.of(Report(findings=list(findings), **report), version="1")


def test_keeps_the_worst_severity_of_each_rule() -> None:
    review = _review(
        _finding("shell-injection", "medium"),
        _finding("shell-injection", "high", location="configfile:script"),
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
    review = _review(
        unanalyzed=["command: $x is not a tool input, its value was not followed"],
        unchecked_locations={"command": NOT_ANALYSED, "configfile:script": NOT_CHECKABLE},
        rewrites={"command": ["decode"]},
    )
    assert review.refused_rules("low") == []


def test_finding_a_patch_lowered_still_refuses_at_its_new_severity(tmp_path: Path) -> None:
    _, _, patch_review = _awk_review(tmp_path, ";", "/")
    review = StaticReview.of(patch_review.after, version="1")
    assert review.refused_rules("medium") == ["nested-interpreter"]
    assert review.refused_rules("high") == []
