"""Declarative cases for the tool security review: synthetic tools, the jobs they refuse and the jobs they run.

``cases.yml`` maps case ids to a tool of ``tools/``, the findings, access patterns, unchecked locations and
uncheckable codes its review must report (:func:`review_problems` compares the two), and ``red`` and
``green`` jobs. A job lists everything a template can read: parameter values, datasets and collections, the
user's account and preferences, and the server's review settings.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import (
    Any,
    Literal,
    NamedTuple,
)

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from galaxy.tool_util.parser import get_tool_source
from galaxy.tool_util.security import review_tool_source
from galaxy.tool_util.security.charsets import SEVERITIES
from galaxy.tool_util.security.classify import (
    classify,
    Uncheckable,
)
from galaxy.tool_util.security.codes import RefusalCode
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

# The file a red job's command creates in its working directory when the review does not stop it.
HARM_MARKER = "harm-marker"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetContext(_Model):
    name: str = "dataset"
    ext: str = "txt"
    content: str = "x\n"
    info: str | None = None
    metadata: dict[str, Any] = {}
    # `name:value` tags; `group:` ones are what $input.groups reads.
    tags: list[str] = []


class ElementContext(_Model):
    identifier: str
    dataset: DatasetContext = DatasetContext()


class CollectionContext(_Model):
    type: Literal["list"] = "list"
    name: str = "collection"
    elements: list[ElementContext]


class UserContext(_Model):
    email: str = "user@example.org"
    username: str = "user"
    preferences: dict[str, str] = {}


class ReviewConfig(_Model):
    mode: Literal["log", "enforce_code", "enforce_data", "enforce_all"] = "enforce_code"
    when_unsure: Literal["strict", "refuse", "log"] = "strict"


class JobExpectation(_Model):
    rejected: bool
    # The codes of the refusal; a red job of a case defaults to the case's code.
    codes: list[RefusalCode] | None = None
    # The codes of the warnings of a job that runs, such as one the server only logs.
    warns: list[RefusalCode] = []
    message_contains: list[str] = []


class JobCase(_Model):
    doc: str | None = None
    # Values of non-data parameters, as the tool state holds them.
    inputs: dict[str, Any] = {}
    datasets: dict[str, DatasetContext] = {}
    collections: dict[str, CollectionContext] = {}
    user: UserContext = UserContext()
    config: ReviewConfig = ReviewConfig()
    # Make a step of the review fail, for the refusals only a bug in it can cause.
    fault: Literal["review", "check", "strict_check"] | None = None
    # Also build the command with the review off and run it: a red job creates HARM_MARKER, a green one does not.
    harm: bool = False
    expect: JobExpectation


class FindingExpectation(_Model):
    """A finding the review reports: every field given must match."""

    rule: Rule
    severity: str | None = None
    location: str | None = None
    accessor: str | None = None
    param: str | None = None
    key: str | None = None
    checkable: bool | None = None

    @field_validator("severity")
    @classmethod
    def _known_severity(cls, severity: str | None) -> str | None:
        if severity is not None and severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {', '.join(SEVERITIES)}")
        return severity


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

    @property
    def rules(self) -> frozenset[Rule]:
        """The rules the case names, in ``serious_rules`` or ``findings``."""
        return frozenset((*(self.serious_rules or ()), *(want.rule for want in self.findings)))


class SpecCase(_Model):
    doc: str
    tool: str
    # The refusal the red jobs show; None for a case of jobs that must run.
    code: RefusalCode | None = None
    review: ReviewExpectation = ReviewExpectation()
    # The job check runs this tool's jobs whatever their values: a sweep would show harm.
    known_bypass: bool = False
    red: list[JobCase] = Field(default_factory=list)
    green: list[JobCase] = Field(default_factory=list)


def load_cases(path: str = CASES_PATH) -> dict[str, SpecCase]:
    with open(path) as fh:
        raw = yaml.safe_load(fh) or {}
    return {case_id: SpecCase.model_validate(case) for case_id, case in raw.items()}


def expected_codes(case: SpecCase, job: JobCase) -> list[RefusalCode]:
    """The codes a job's refusal must carry: none for a job that runs."""
    if not job.expect.rejected:
        return []
    if job.expect.codes is not None:
        return sorted(job.expect.codes)
    assert case.code is not None, "a rejected job needs codes or a case code"
    return [case.code]


def expected_warnings(case: SpecCase, job: JobCase) -> list[RefusalCode]:
    """The codes of the warnings Galaxy logs for a job: those of its refusal, or those it only logs."""
    return expected_codes(case, job) if job.expect.rejected else sorted(job.expect.warns)


def tool_path(tool: str) -> str:
    return os.path.join(TOOLS_DIRECTORY, tool)


class SpecJob(NamedTuple):
    case_id: str
    # "red" or "green"
    color: str
    position: int
    job: JobCase


def iter_jobs(cases: dict[str, SpecCase]) -> Iterator[SpecJob]:
    """Every job of the cases."""
    for case_id, case in cases.items():
        for color in ("red", "green"):
            for index, job in enumerate(getattr(case, color)):
                yield SpecJob(case_id, color, index, job)


# Values that start a shell command from single quotes, double quotes, or no quotes.
SWEEP_PAYLOADS = (
    f"a';touch {HARM_MARKER};'",
    f'a";touch {HARM_MARKER};"',
    f"a;touch {HARM_MARKER}",
    f"$(touch {HARM_MARKER})",
    f"`touch {HARM_MARKER}`",
)
# Preferences a sweep also sets, whether or not the job does.
SWEEP_PREFERENCES = ("spec|label", "label")


class SweepJob(NamedTuple):
    case_id: str
    # The green job of the case it changes, and what it changes.
    base: int
    slot: str
    payload_index: int
    job: JobCase


def sweep_jobs(cases: dict[str, SpecCase]) -> Iterator[SweepJob]:
    """Each green job with a harm check, under the default settings, with one value a template reads set to a payload.

    Every such job must be refused or leave no HARM_MARKER: a sweep does not trust the review to know what a
    tool reads. Its payloads are shell code, so it shows nothing for values a tool writes into another language.
    """
    for case_id, case in cases.items():
        if case.known_bypass:
            continue
        bases = [(i, job) for i, job in enumerate(case.green) if job.harm and job.fault is None]
        for position, (index, job) in enumerate(bases):
            base = job.model_copy(update={"config": ReviewConfig(), "doc": None})
            # The user's account and the extra preferences do not depend on the job: once per case is enough.
            for slot in _slots(base, with_user=position == 0):
                for payload_index, payload in enumerate(SWEEP_PAYLOADS):
                    swept = base.model_copy(deep=True)
                    _set(swept, slot, payload)
                    yield SweepJob(case_id, index, slot, payload_index, swept)


def _slots(job: JobCase, with_user: bool) -> Iterator[str]:
    """The text values of a job, as dotted paths ``_set`` understands."""
    for name, value in job.inputs.items():
        if isinstance(value, str):
            yield f"inputs.{name}"
    for name, dataset in job.datasets.items():
        yield from _dataset_slots(f"datasets.{name}", dataset)
    for name, collection in job.collections.items():
        for index, element in enumerate(collection.elements):
            yield f"collections.{name}.{index}.identifier"
            yield from _dataset_slots(f"collections.{name}.{index}.dataset", element.dataset)
    for key in dict.fromkeys((*job.user.preferences, *(SWEEP_PREFERENCES if with_user else ()))):
        yield f"preferences.{key}"
    if with_user:
        yield "user.email"
        yield "user.username"


def _dataset_slots(path: str, dataset: DatasetContext) -> Iterator[str]:
    yield from (f"{path}.{field}" for field in ("name", "info", "content", "tags"))
    for key, value in dataset.metadata.items():
        if isinstance(value, (str, list)):
            yield f"{path}.metadata.{key}"


def _set(job: JobCase, slot: str, payload: str) -> None:
    kind, _, rest = slot.partition(".")
    if kind == "inputs":
        job.inputs[rest] = payload
    elif kind == "preferences":
        job.user.preferences[rest] = payload
    elif kind == "user":
        # An email address keeps its domain.
        setattr(job.user, rest, f"{payload}@example.org" if rest == "email" else payload)
    elif kind == "datasets":
        name, _, field = rest.partition(".")
        _set_dataset(job.datasets[name], field, payload)
    else:
        name, index, field = rest.split(".", 2)
        element = job.collections[name].elements[int(index)]
        if field == "identifier":
            element.identifier = payload
        else:
            _set_dataset(element.dataset, field.partition(".")[2], payload)


def _set_dataset(dataset: DatasetContext, field: str, payload: str) -> None:
    if field == "content":
        dataset.content = f"{payload}\n"
    elif field == "tags":
        dataset.tags = [*dataset.tags, f"group:{payload}", f"name:{payload}"]
    elif field.startswith("metadata."):
        key = field.partition(".")[2]
        dataset.metadata[key] = [payload] if isinstance(dataset.metadata[key], list) else payload
    else:
        setattr(dataset, field, payload)


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
