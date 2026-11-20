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
                self.findings[i] = replace(first, more_lines=tuple(sorted(lines)))
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
            "findings": [asdict(f) for f in self.sorted()],
            "unanalyzed": self.unanalyzed,
        }
