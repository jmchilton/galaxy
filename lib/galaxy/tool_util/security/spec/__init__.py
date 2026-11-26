"""Declarative cases for the tool security review: synthetic tools and what the review reports for them.

``cases.yml`` maps case ids to a tool of ``tools/`` and the findings, access patterns, unchecked
locations and uncheckable codes its review must report; :func:`review_problems` compares the two.
"""

from __future__ import annotations

import os

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    field_validator,
)

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.classify import (
    classify,
    Uncheckable,
)
from galaxy.tool_util.security.patterns import (
    access_patterns,
    PatternCode,
)
from galaxy.tool_util.security.report import (
    Finding,
    serious_findings,
)
from galaxy.tool_util.security.rules import Rule

SPEC_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIRECTORY = os.path.join(SPEC_DIRECTORY, "tools")
CASES_PATH = os.path.join(SPEC_DIRECTORY, "cases.yml")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FindingExpectation(_Model):
    """A finding the review reports: every field given must match."""

    rule: Rule
    severity: str | None = None
    location: str | None = None
    accessor: str | None = None
    param: str | None = None
    key: str | None = None
    checkable: bool | None = None


class ReviewExpectation(_Model):
    findings: list[FindingExpectation] = []
    # Exactly the rules of the high and critical vulnerabilities, when given.
    serious_rules: list[Rule] | None = None
    # Exactly these, when given.
    unchecked_locations: dict[str, str] | None = None
    rewrites: bool | None = None
    # Exactly the access patterns of the tool.
    patterns: list[PatternCode] = []
    # Exactly the uncheckable codes of classify(), when given.
    codes: list[Uncheckable] | None = None

    @field_validator("codes")
    @classmethod
    def _classify_returns(cls, codes: list[Uncheckable] | None) -> list[Uncheckable] | None:
        if codes and Uncheckable.REVIEW_FAILED in codes:
            raise ValueError(f"classify() never returns {Uncheckable.REVIEW_FAILED}")
        return codes


class SpecCase(_Model):
    doc: str
    tool: str
    review: ReviewExpectation = ReviewExpectation()


def load_cases(path: str = CASES_PATH) -> dict[str, SpecCase]:
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {case_id: SpecCase.model_validate(case) for case_id, case in raw.items()}


def tool_path(tool: str) -> str:
    return os.path.join(TOOLS_DIRECTORY, tool)


def review_problems(case: SpecCase) -> list[str]:
    """What the review of the case's tool reports differently from the case's ``review``; empty when it agrees."""
    report = review_tool_source(get_tool_source(tool_path(case.tool)))
    expected = case.review
    problems = []
    for want in expected.findings:
        if not any(_matches(want, finding) for finding in report.findings):
            problems.append(f"no finding matches {want.model_dump(exclude_none=True)}")
    if expected.serious_rules is not None:
        serious = sorted({f.rule for f in serious_findings(report)})
        if serious != sorted(expected.serious_rules):
            problems.append(f"serious rules are {serious}, expected {[str(r) for r in sorted(expected.serious_rules)]}")
    if expected.unchecked_locations is not None and report.unchecked_locations != expected.unchecked_locations:
        problems.append(f"unchecked locations are {report.unchecked_locations}")
    if expected.rewrites is not None and bool(report.rewrites) != expected.rewrites:
        problems.append(f"rewrites are {report.rewrites}")
    patterns = sorted(access_patterns(report))
    if patterns != sorted(expected.patterns):
        problems.append(f"access patterns are {[p.value for p in patterns]}")
    if expected.codes is not None:
        codes = classify(report).codes
        if codes != sorted(expected.codes):
            problems.append(f"uncheckable codes are {[c.value for c in codes]}")
    return problems


def _matches(want: FindingExpectation, finding: Finding) -> bool:
    if finding.rule != want.rule:
        return False
    for field in ("severity", "location"):
        value = getattr(want, field)
        if value is not None and getattr(finding, field) != value:
            return False
    if want.checkable is not None and finding.checkable != want.checkable:
        return False
    if want.accessor is None and want.param is None and want.key is None:
        return True
    return any(
        (want.accessor is None or ref.accessor == want.accessor)
        and (want.param is None or ref.param == want.param)
        and (want.key is None or ref.key == want.key)
        for ref in finding.refs
    )
