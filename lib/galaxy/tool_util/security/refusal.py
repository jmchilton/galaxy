"""The static review kept with a loaded tool, and which of its findings refuse the tool's jobs."""

from __future__ import annotations

from pydantic import BaseModel

from .charsets import (
    at_or_above,
    worst,
)
from .report import Report

# The refusal code of a job of a tool whose static review refuses it.
STATIC_FINDINGS = "static-findings"


class StaticReview(BaseModel):
    """The worst severity of each rule a tool's review found; ``error`` names what the review raised."""

    severities: dict[str, str] = {}
    error: str | None = None
    # The Galaxy version that reviewed the tool.
    version: str

    @classmethod
    def of(cls, report: Report, version: str) -> StaticReview:
        severities: dict[str, str] = {}
        for finding in report.findings:
            severities[finding.rule] = worst(severities.get(finding.rule, finding.severity), finding.severity)
        return cls(severities=dict(sorted(severities.items())), version=version)

    def refused_rules(self, threshold: str) -> list[str]:
        """The rules with a finding at or above ``threshold``; uncheckable codes and a failed review refuse nothing."""
        return [rule for rule, severity in self.severities.items() if at_or_above(severity, threshold)]
