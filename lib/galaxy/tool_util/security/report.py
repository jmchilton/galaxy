"""Findings and the per-tool report the review produces."""

from __future__ import annotations

from dataclasses import (
    asdict,
    dataclass,
    field,
    replace,
)
from typing import (
    Any,
)

from .charsets import (
    SEVERITIES,
    worst,
)

# What a finding is about. A vulnerability lets a *user* of the tool attack the server;
# a capability is something the tool *author* made the tool able to do.
VULNERABILITY = "vulnerability"
CAPABILITY = "capability"


class ReviewTimeout(Exception):
    """The review ran past the deadline it was given."""


# How a template reads a user-controlled value (SourceRef.accessor). Each names the value Galaxy
# puts into the template namespace, so the value of a job can be compared with a finding.
TEXT = "text"  # the parameter as written by `$param`: the sanitized string
RAW = "raw"  # the submitted value, through `$param.value` or a string method
ELEMENT_IDENTIFIER = "element_identifier"  # element identifiers of a data or collection input, and collection names
DATASET_ATTRIBUTE = "dataset_attribute"  # an attribute of the input datasets, such as their name (key)
METADATA = "metadata"  # a metadata element of the input datasets (key)
GROUP_TAGS = "group_tags"  # the group: tags of the input datasets
SPECIAL = "special"  # a value Galaxy adds for the user, such as $__user_email__ (key)
OPAQUE = "opaque"  # an object the template can read anything from: no single value to compare
ACCESSORS = (TEXT, RAW, ELEMENT_IDENTIFIER, DATASET_ATTRIBUTE, METADATA, GROUP_TAGS, SPECIAL, OPAQUE)


@dataclass(frozen=True)
class SourceRef:
    """Where a user-controlled value comes from: the input (its path, `cond.param`) and how it is read."""

    accessor: str
    param: str | None = None
    key: str | None = None

    @property
    def param_path(self) -> tuple[str, ...]:
        return tuple(self.param.split(".")) if self.param else ()


class Source(str):
    """The human-readable description of a source, carrying its :class:`SourceRef`.

    Compares, hashes and sorts as the plain string, so the analysis treats it exactly like one;
    the model gives the same reference to every source it describes with the same text.
    """

    ref: SourceRef

    def __new__(cls, text: str, ref: SourceRef) -> Source:
        source = super().__new__(cls, text)
        source.ref = ref
        return source

    def __reduce__(self) -> Any:
        return (Source, (str(self), self.ref))


def sorted_refs(refs: Any) -> tuple[SourceRef, ...]:
    return tuple(sorted(set(refs), key=lambda r: (r.accessor, r.param or "", r.key or "")))


def source_refs(sources: Any) -> tuple[SourceRef, ...]:
    """The references of the sources of a value."""
    return sorted_refs(s.ref for s in sources if isinstance(s, Source))


@dataclass(frozen=True)
class Finding:
    rule: str
    kind: str
    severity: str
    message: str
    location: str = "command"
    line: int | None = None
    expr: str | None = None
    source: str | None = None
    context: str | None = None
    chars: str | None = None
    # Further template lines where the same value lands in the same kind of place.
    more_lines: tuple[int, ...] = ()
    # A language model's second opinion (see judge.py). Advisory: it never changes rule or severity.
    assessment: dict[str, Any] | None = None
    # Every source of the value (`source` shows the first three), and the characters at least one of
    # which a value must contain to leave the place it is written. Empty when no character decides it,
    # as for a value that chooses the program to run.
    refs: tuple[SourceRef, ...] = ()
    breakout: frozenset[str] = frozenset()
    # When not empty, a value must also contain one of these characters.
    requires: frozenset[str] = frozenset()
    # Sources whose value the template rewrites in a way that can bring in a breakout character
    # (str.replace, re.sub, a decoder, an unknown function): their characters decide nothing.
    unchecked: tuple[SourceRef, ...] = ()

    @property
    def checkable(self) -> bool:
        """Whether a character test on the values of the job can tell that this finding applies."""
        return bool(self.breakout) and any(ref.accessor != OPAQUE and ref not in self.unchecked for ref in self.refs)

    def key(self) -> tuple[Any, ...]:
        if self.kind == VULNERABILITY:
            return (self.rule, self.location, self.source, self.context)
        return (self.rule, self.location, self.expr)


@dataclass
class Report:
    tool_id: str | None = None
    findings: list[Finding] = field(default_factory=list)
    # Template sites the analysis could not follow; an honest list of what was not checked.
    unanalyzed: list[str] = field(default_factory=list)

    def add(self, finding: Finding) -> None:
        for i, existing in enumerate(self.findings):
            if existing.key() == finding.key():
                first, second = (
                    (finding, existing)
                    if worst(finding.severity, existing.severity) != existing.severity
                    else (existing, finding)
                )
                candidates = (first.line, second.line, *first.more_lines, *second.more_lines)
                lines = {line for line in candidates if line is not None and line != first.line}
                self.findings[i] = replace(
                    first,
                    more_lines=tuple(sorted(lines)),
                    refs=sorted_refs((*first.refs, *second.refs)),
                    breakout=first.breakout | second.breakout,
                    # Either finding's condition implies the merged one.
                    requires=(first.requires | second.requires if first.requires and second.requires else frozenset()),
                    unchecked=sorted_refs((*first.unchecked, *second.unchecked)),
                )
                return
        self.findings.append(finding)

    def assess(self, finding: Finding, assessment: dict[str, Any]) -> None:
        self.findings = [replace(f, assessment=assessment) if f is finding else f for f in self.findings]

    def sorted(self) -> list[Finding]:
        return sorted(
            self.findings,
            key=lambda f: (-SEVERITIES.index(f.severity), f.kind, f.location, f.line or 0, f.rule),
        )

    @property
    def max_severity(self) -> str | None:
        severity = None
        for finding in self.findings:
            severity = finding.severity if severity is None else worst(severity, finding.severity)
        return severity

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "max_severity": self.max_severity,
            "findings": [_finding_to_dict(f) for f in self.sorted()],
            "unanalyzed": self.unanalyzed,
        }

    @classmethod
    def from_dict(cls, as_dict: dict[str, Any]) -> Report:
        """The report :meth:`to_dict` wrote."""
        report = cls(tool_id=as_dict.get("tool_id"), unanalyzed=list(as_dict.get("unanalyzed") or []))
        for f in as_dict.get("findings") or []:
            f = dict(f)
            f["more_lines"] = tuple(f.get("more_lines") or ())
            f["refs"] = tuple(SourceRef(**ref) for ref in f.get("refs") or ())
            f["unchecked"] = tuple(SourceRef(**ref) for ref in f.get("unchecked") or ())
            f["breakout"] = frozenset(f.get("breakout") or ())
            f["requires"] = frozenset(f.get("requires") or ())
            report.findings.append(Finding(**f))
        return report


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    as_dict = asdict(finding)
    as_dict["more_lines"] = list(finding.more_lines)
    as_dict["breakout"] = sorted(finding.breakout)
    as_dict["requires"] = sorted(finding.requires)
    return as_dict
