"""Security review of a tool before and after its tool patches."""

from dataclasses import dataclass
from typing import Any

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import (
    patches_as_dicts,
    ToolPatchDatabase,
    ToolPatchInfo,
)
from . import review_tool_source
from .charsets import SEVERITIES
from .classify import classify
from .report import (
    Finding,
    finding_to_dict,
    Report,
    sorted_refs,
)

FindingMatch = tuple[Any, ...]


def finding_match(finding: Finding) -> FindingMatch:
    """Identity of a finding across a patch: rule, place, how the value lands there and what it reads."""
    return (finding.rule, finding.kind, finding.location, finding.context, sorted_refs(finding.refs) or finding.expr)


def _notes(report: Report) -> dict[tuple[str, str], str]:
    """The CLI's NOTE lines for a report, keyed by unanalyzed part, unchecked location or uncheckable code."""
    classification = classify(report)
    notes = {("unanalyzed", note): note for note in report.unanalyzed}
    for location, why in classification.unchecked_locations.items():
        notes[("unchecked", location)] = f"unchecked {location}: {why}"
    for code, why in classification.reasons.items():
        notes[("code", code)] = f"{code}: {why}"
    return notes


@dataclass
class PatchReview:
    before: Report
    after: Report
    patched: ToolSource
    patch: ToolPatchInfo | None

    @property
    def cleared(self) -> list[Finding]:
        """The findings with no match after the patch; a lowered severity is not cleared."""
        after = {finding_match(f) for f in self.after.findings}
        return [f for f in self.before.sorted() if finding_match(f) not in after]

    @property
    def introduced(self) -> list[Finding]:
        """The findings with no match before the patch, or of a worse severity than every match there."""
        worst: dict[FindingMatch, int] = {}
        for f in self.before.findings:
            match = finding_match(f)
            worst[match] = max(worst.get(match, -1), SEVERITIES.index(f.severity))
        return [f for f in self.after.sorted() if SEVERITIES.index(f.severity) > worst.get(finding_match(f), -1)]

    @property
    def notes_added(self) -> list[str]:
        """NOTE lines only after the patch: a template part it broke, a location or code it made uncheckable."""
        before = _notes(self.before)
        return [note for key, note in _notes(self.after).items() if key not in before]

    @property
    def regressed(self) -> bool:
        """The patch introduced a finding or left part of the tool unreviewable."""
        return bool(self.introduced or self.notes_added)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patches": patches_as_dicts(self.patch),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "cleared": [finding_to_dict(f) for f in self.cleared],
            "introduced": [finding_to_dict(f) for f in self.introduced],
            "notes_added": self.notes_added,
        }


def review_patches(tool_source: ToolSource, db: ToolPatchDatabase, guid: str | None = None) -> PatchReview:
    """Review ``tool_source`` unpatched and as ``db`` patches it; findings are matched by :func:`finding_match`."""
    before = review_tool_source(tool_source)
    patched = db.apply_patches(tool_source, guid=guid)
    after = before if patched is tool_source else review_tool_source(patched)
    return PatchReview(before=before, after=after, patched=patched, patch=patched.patch_state)
