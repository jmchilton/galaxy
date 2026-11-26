"""Security review of a tool before and after its tool patches."""

from dataclasses import dataclass
from typing import Any

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import (
    patches_as_dicts,
    PatchState,
    ToolPatchDatabase,
    ToolPatchInfo,
)
from galaxy.tool_util.patches.engine import (
    APPLIED,
    MISMATCH,
)
from galaxy.tool_util.patches.model import SECURITY
from . import review_tool_source
from .charsets import SEVERITIES
from .classify import (
    Classification,
    classify,
)
from .report import (
    CAPABILITY,
    Finding,
    finding_to_dict,
    Report,
    sorted_refs,
    SourceRef,
)

FindingMatch = tuple[str, str, str, str | None, tuple[SourceRef, ...] | str | None]


def finding_match(finding: Finding) -> FindingMatch:
    """Identity of a finding across a patch: rule, place, how the value lands there and what it reads or names."""
    # A capability's expr can be its whole #import line; its message names the module.
    named = finding.message if finding.kind == CAPABILITY else finding.expr
    return (finding.rule, finding.kind, finding.location, finding.context, sorted_refs(finding.refs) or named)


def note_lines(report: Report, classification: Classification) -> list[tuple[tuple[str, str], str]]:
    """The NOTE lines of a report in order, repeats kept, each keyed by unanalyzed part, location or code."""
    notes = [(("unanalyzed", note), note) for note in report.unanalyzed]
    notes += [
        (("unchecked", loc), f"unchecked {loc}: {why}") for loc, why in classification.unchecked_locations.items()
    ]
    notes += [(("code", code), f"{code}: {why}") for code, why in classification.reasons.items()]
    return notes


def report_dict(report: Report, classification: Classification) -> dict[str, Any]:
    """A report with its uncheckable codes and classified unchecked locations, as the CLI's JSON gives it."""
    return {
        **report.to_dict(),
        "codes": classification.codes,
        "uncheckable_locations": classification.unchecked_locations,
    }


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
        before = {key for key, _ in note_lines(self.before, classify(self.before))}
        added = [(key, note) for key, note in note_lines(self.after, classify(self.after)) if key not in before]
        return list(dict(added).values())

    @property
    def states(self) -> list[PatchState]:
        return self.patch.states if self.patch else []

    @property
    def mismatched(self) -> list[PatchState]:
        """The security patch units whose ops no longer match the tool."""
        return [s for s in self.states if s.state == MISMATCH and s.kind == SECURITY]

    @property
    def uncleared(self) -> bool:
        """A security patch unit applied but the review clears no finding."""
        return any(s.state == APPLIED and s.kind == SECURITY for s in self.states) and not self.cleared

    @property
    def regressed(self) -> bool:
        """The patch introduced a finding or left part of the tool unreviewable."""
        return bool(self.introduced or self.notes_added)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patches": patches_as_dicts(self.patch),
            "before": report_dict(self.before, classify(self.before)),
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
