"""Declarative cases for the tool security review: real tools, the jobs they refuse and the jobs they run.

``cases.yml`` maps case ids to a tool of ``tools/``, what the review reports for it, and ``red`` and
``green`` jobs. A job lists everything a template can read: parameter values, datasets and
collections, the user's account and preferences, and the server's review settings.
"""

from __future__ import annotations

import os
from typing import (
    Any,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
)

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)
from typing_extensions import Literal

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.codes import RefusalCode
from galaxy.tool_util.security.report import serious_findings

SPEC_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIRECTORY = os.path.join(SPEC_DIRECTORY, "tools")
CASES_PATH = os.path.join(SPEC_DIRECTORY, "cases.yml")

# The file a red job's command creates in its working directory when the review does not stop it.
HARM_MARKER = "harm-marker"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetContext(_Model):
    name: str = "dataset"
    ext: str = "txt"
    content: str = "x\n"
    info: Optional[str] = None
    metadata: Dict[str, Any] = {}
    # `name:value` tags; `group:` ones are what $input.groups reads.
    tags: List[str] = []


class ElementContext(_Model):
    identifier: str
    dataset: DatasetContext = DatasetContext()


class CollectionContext(_Model):
    type: Literal["list"] = "list"
    name: str = "collection"
    elements: List[ElementContext]


class UserContext(_Model):
    email: str = "user@example.org"
    username: str = "user"
    preferences: Dict[str, str] = {}


class ReviewConfig(_Model):
    mode: Literal["log", "enforce"] = "enforce"
    strict_when_unsure: bool = True


class JobExpectation(_Model):
    rejected: bool
    # The codes of the refusal; a red job of a case defaults to the case's code.
    codes: Optional[List[RefusalCode]] = None
    message_contains: List[str] = []


class JobCase(_Model):
    doc: Optional[str] = None
    # Values of non-data parameters, as the tool state holds them.
    inputs: Dict[str, Any] = {}
    datasets: Dict[str, DatasetContext] = {}
    collections: Dict[str, CollectionContext] = {}
    user: UserContext = UserContext()
    config: ReviewConfig = ReviewConfig()
    # Make a step of the review fail, for the refusals only a bug in it can cause.
    fault: Optional[Literal["review", "check", "strict_check"]] = None
    # Also build the command with the review off and run it: a red job creates HARM_MARKER, a green one does not.
    harm: bool = False
    expect: JobExpectation


class FindingExpectation(_Model):
    """A finding the review reports: every field given must match."""

    rule: str
    severity: Optional[str] = None
    location: Optional[str] = None
    accessor: Optional[str] = None
    param: Optional[str] = None
    key: Optional[str] = None
    checkable: Optional[bool] = None


class ReviewExpectation(_Model):
    findings: List[FindingExpectation] = []
    # Exactly the rules of the high and critical vulnerabilities, when given.
    serious_rules: Optional[List[str]] = None
    # Exactly these, when given.
    unchecked_locations: Optional[Dict[str, str]] = None
    rewrites: Optional[bool] = None


class SpecCase(_Model):
    doc: str
    tool: str
    # The refusal the red jobs show; None for a case of jobs that must run.
    code: Optional[RefusalCode] = None
    review: ReviewExpectation = ReviewExpectation()
    red: List[JobCase] = []
    green: List[JobCase] = Field(default_factory=list)


def load_cases(path: str = CASES_PATH) -> Dict[str, SpecCase]:
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {case_id: SpecCase.model_validate(case) for case_id, case in raw.items()}


def expected_codes(case: SpecCase, job: JobCase) -> List[RefusalCode]:
    """The codes a job's refusal must carry: none for a job that runs."""
    if not job.expect.rejected:
        return []
    if job.expect.codes is not None:
        return sorted(job.expect.codes)
    assert case.code is not None, "a rejected job needs codes or a case code"
    return [case.code]


def tool_path(tool: str) -> str:
    return os.path.join(TOOLS_DIRECTORY, tool)


class SpecJob(NamedTuple):
    case_id: str
    # "red" or "green"
    color: str
    position: int
    job: JobCase


def iter_jobs(cases: Dict[str, SpecCase]) -> Iterator[SpecJob]:
    """Every job of the cases."""
    for case_id, case in cases.items():
        for color in ("red", "green"):
            for index, job in enumerate(getattr(case, color)):
                yield SpecJob(case_id, color, index, job)


def review_problems(case: SpecCase) -> List[str]:
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
            problems.append(f"serious rules are {serious}, expected {sorted(expected.serious_rules)}")
    if expected.unchecked_locations is not None and report.unchecked_locations != expected.unchecked_locations:
        problems.append(f"unchecked locations are {report.unchecked_locations}")
    if expected.rewrites is not None and bool(report.rewrites) != expected.rewrites:
        problems.append(f"rewrites are {report.rewrites}")
    return problems


def _matches(want: FindingExpectation, finding: Any) -> bool:
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
