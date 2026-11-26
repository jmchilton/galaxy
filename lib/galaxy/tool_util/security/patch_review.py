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


def _notes(report: Report) -> list[str]:
    """The report's unanalyzed parts and unchecked locations, as the CLI's NOTE lines word them."""
    return report.unanalyzed + [f"unchecked {k}: {v}" for k, v in sorted(report.unchecked_locations.items())]


def _gained(before: list[Finding], after: list[Finding]) -> list[Finding]:
    before_keys = {finding_match(f) for f in before}
    return [f for f in after if finding_match(f) not in before_keys]


@dataclass
class PatchReview:
    before: Report
    after: Report
    patched: ToolSource
    patch: ToolPatchInfo | None

    @property
    def cleared(self) -> list[Finding]:
        return _gained(self.after.sorted(), self.before.sorted())

    @property
    def introduced(self) -> list[Finding]:
        return _gained(self.before.sorted(), self.after.sorted())

    @property
    def unanalyzed_added(self) -> list[str]:
        """Template parts the review can follow only before the patch, such as a template the patch broke."""
        before = set(_notes(self.before))
        return [note for note in _notes(self.after) if note not in before]

    @property
    def regressed(self) -> bool:
        """The patch introduced a finding or left part of the tool unreviewable."""
        return bool(self.introduced or self.unanalyzed_added)

    def to_dict(self) -> dict[str, Any]:
        return {
            "patches": patches_as_dicts(self.patch),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "cleared": [finding_to_dict(f) for f in self.cleared],
            "introduced": [finding_to_dict(f) for f in self.introduced],
            "unanalyzed_added": self.unanalyzed_added,
        }


def review_patches(tool_source: ToolSource, db: ToolPatchDatabase, guid: str | None = None) -> PatchReview:
    """Review ``tool_source`` unpatched and as ``db`` patches it; findings are matched by :func:`finding_match`."""
    before = review_tool_source(tool_source)
    patched = db.apply_patches(tool_source, guid=guid)
    after = before if patched is tool_source else review_tool_source(patched)
    return PatchReview(before=before, after=after, patched=patched, patch=patched.patch_state)
