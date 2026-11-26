"""Findings and the per-tool report the review produces."""

from __future__ import annotations

from collections.abc import Iterable
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
    CRITICAL,
    HIGH,
    SEVERITIES,
    stricter,
    worst,
)

# What a finding is about. A vulnerability lets a *user* of the tool attack the server;
# a capability is something the tool *author* made the tool able to do.
VULNERABILITY = "vulnerability"
CAPABILITY = "capability"


# Breakout characters that close or escape quotes: a value that can bring one where it is written
# changes how the rest of its line is quoted.
QUOTE_CLOSERS = frozenset("'\"`\\")


# How a template reads a user-controlled value (SourceRef.accessor). Each names the value Galaxy
# puts into the template namespace, so the value of a job can be compared with a finding.
TEXT = "text"  # the parameter as written by `$param`: the sanitized string
RAW = "raw"  # the submitted value, through `$param.value` or a string method
ELEMENT_IDENTIFIER = "element_identifier"  # element identifiers of a data or collection input, and collection names
DATASET_ATTRIBUTE = "dataset_attribute"  # an attribute of the input datasets, such as their name (key)
METADATA = "metadata"  # a metadata element of the input datasets (key)
GROUP_TAGS = "group_tags"  # the group: tags of the input datasets
SPECIAL = "special"  # a value Galaxy adds for the user, such as $__user_email__ (key)
DATASET_CONTENT = "dataset_content"  # the content of the input datasets, which the template reads with open()
USER_PREFERENCE = "user_preference"  # a preference the user set, $__user__.extra_preferences (key)
# An attribute (key) or a metadata element (key) of the input datasets as users set them, through
# `$input.unsanitized`: not sanitized.
RAW_DATASET_ATTRIBUTE = "raw_dataset_attribute"
RAW_METADATA = "raw_metadata"
OPAQUE = "opaque"  # an object the template can read anything from: no single value to compare
# Why the values of a location cannot be checked (Report.unchecked_locations).
NOT_ANALYSED = "parts of it were not analysed"
RUNS_TEXT = "it sends text to a shell to run"
# Capability findings of a template that sends text to a program that runs it.
RUNS_TEXT_RULES = frozenset(("capability-pipe-to-shell",))
# The capability finding of a template that reaches objects by name (getattr).
REFLECTION_RULE = "template-reflection"
# The capability finding of a tool that turns the sanitizer off.
SANITIZE_OFF = "tool-sanitize-off"
# Capabilities with which a template runs code or reads text that the job does not carry.
CODE_CAPABILITIES = frozenset(
    (
        "template-exec",
        "template-compile-exec",
        "template-file-io",
        "template-network",
        REFLECTION_RULE,
        "template-app-access",
        "template-model-access",
    )
)


# The severities of serious findings, the ones of the code level (charsets.level_of) unless a verdict
# says otherwise. The characters of medium findings, a space, a slash or a quote, are common in element
# identifiers and dataset names.
CHECKED_SEVERITIES = frozenset((HIGH, CRITICAL))


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


def rendered(location: str) -> bool:
    """Whether a location of the review is the command or a configfile: a template rendered into what the job runs."""
    return location == "command" or location.startswith("configfile:")


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
    # Characters of the value that close or open quotes where it is written, which flips the
    # quoting of the rest of the line for every other value (see Report.writes).
    closes: frozenset[str] = frozenset()
    # The finding holds only when another value of the template brings a character that closes
    # or escapes a quote (a value after one that can end in a backslash).
    needs_closer: bool = False
    # Sources whose value the template rewrites in a way that can bring in a breakout character
    # (str.replace, re.sub, a decoder, an unknown function): their characters decide nothing.
    unchecked: tuple[SourceRef, ...] = ()
    # The level of a vulnerability (charsets.LEVELS), and what a value must also hold at the data
    # level (charsets.DATA_HARM).
    level: str | None = None
    data_requires: frozenset[str] = frozenset()

    @property
    def checkable(self) -> bool:
        """Whether a character test on the values of the job can tell that this finding applies."""
        return bool(self.breakout or self.closes) and any(
            ref.accessor != OPAQUE and ref not in self.unchecked for ref in self.refs
        )

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
    # Every user value each template (location) writes, by source, with the characters that do
    # harm in it once a stray quote of another value has left it outside any quotes. A location
    # whose values the job check cannot judge is left out.
    writes: dict[str, dict[SourceRef, frozenset[str]]] = field(default_factory=dict)
    # Quote characters of values that close or open quotes where no finding says so: repr() or
    # json.dumps() write a quote that closes the string around the value, after which a quote of
    # the value's own opens new quotes.
    closers: dict[str, dict[SourceRef, frozenset[str]]] = field(default_factory=dict)
    # Locations whose user values no character test can judge, with the reason: parts of the
    # template were not analysed, or it sends text to a program that runs it. Their findings are
    # not checkable, and their writes are left out.
    unchecked_locations: dict[str, str] = field(default_factory=dict)
    # Template code that can turn a plain value into one that is not (chr(), a decoder, a re.sub or
    # .replace whose text is not literal or that rewrites a value template code changed), by location.
    rewrites: dict[str, list[str]] = field(default_factory=dict)
    # Literal rewrites of a source's own value (`$x.replace('"', '\\"')`), as (trigger, added): the job
    # check adds the characters ``added`` to a job value that holds one of ``trigger``.
    rewritten: dict[SourceRef, list[tuple[frozenset[str], frozenset[str]]]] = field(default_factory=dict)
    # The sources of the user values each template (location) reads, also where no character test
    # can judge them: what the strict check of a job reads. METADATA and USER_PREFERENCE with
    # key=None stand for any metadata element and any preference.
    reads: dict[str, list[SourceRef]] = field(default_factory=dict)

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
                    closes=first.closes | second.closes,
                    needs_closer=first.needs_closer and second.needs_closer,
                    unchecked=sorted_refs((*first.unchecked, *second.unchecked)),
                    level=stricter(first.level, second.level),
                    # Either finding's condition implies the merged one.
                    data_requires=(
                        first.data_requires | second.data_requires
                        if first.data_requires and second.data_requires
                        else frozenset()
                    ),
                )
                return
        self.findings.append(finding)

    def add_rewrite(self, location: str, name: str) -> None:
        found = self.rewrites.setdefault(location, [])
        if name not in found:
            found.append(name)

    def added_by_rewrites(self, ref: SourceRef, chars: Iterable[str]) -> frozenset[str]:
        """What the literal rewrites of a source add to a value of it that holds ``chars``."""
        held = frozenset(chars)
        return frozenset().union(*(added for trigger, added in self.rewritten.get(ref, ()) if held & trigger))

    def assess(self, finding: Finding, assessment: dict[str, Any]) -> None:
        self.findings = [replace(f, assessment=assessment) if f is finding else f for f in self.findings]

    def sorted(self) -> list[Finding]:
        return sorted(
            self.findings,
            # Down to the message: findings that tie otherwise come in the order the analysis met them.
            key=lambda f: (-SEVERITIES.index(f.severity), f.kind, f.location, f.line or 0, f.rule, f.message),
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
            "writes": _by_location(self.writes),
            "closers": _by_location(self.closers),
            "unchecked_locations": dict(sorted(self.unchecked_locations.items())),
            "rewrites": {location: sorted(found) for location, found in sorted(self.rewrites.items())},
            "rewritten": [
                {"ref": asdict(ref), "trigger": sorted(trigger), "added": sorted(added)}
                for ref, rules in sorted(self.rewritten.items(), key=lambda item: repr(item[0]))
                for trigger, added in rules
            ],
            "reads": {location: [asdict(ref) for ref in refs] for location, refs in sorted(self.reads.items())},
        }


def _by_location(chars_by_location: dict[str, dict[SourceRef, frozenset[str]]]) -> list[dict[str, Any]]:
    return [
        {"location": location, "ref": asdict(ref), "chars": sorted(chars)}
        for location, refs in sorted(chars_by_location.items())
        for ref, chars in sorted(refs.items(), key=lambda item: repr(item[0]))
    ]


def _finding_to_dict(finding: Finding) -> dict[str, Any]:
    as_dict = asdict(finding)
    as_dict["more_lines"] = list(finding.more_lines)
    as_dict["breakout"] = sorted(finding.breakout)
    as_dict["requires"] = sorted(finding.requires)
    as_dict["closes"] = sorted(finding.closes)
    as_dict["data_requires"] = sorted(finding.data_requires)
    return as_dict


def serious_findings(report: Report) -> list[Finding]:
    """The high and critical vulnerability findings, the ones checked against job values, most severe first."""
    return [f for f in report.sorted() if f.kind == VULNERABILITY and f.severity in CHECKED_SEVERITIES]
