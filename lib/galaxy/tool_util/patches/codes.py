"""Advisory codes Galaxy generates from site policy and mismatches."""

from string import Formatter
from typing import Any

from .model import CodeEntry

REPRODUCIBILITY_ABOVE_CAP = "reproducibility_above_cap"
REQUIREMENT_CHANGES_DISABLED = "requirement_changes_disabled"
REVISION_MISMATCH = "revision_mismatch"

GENERATED_CODES: dict[str, CodeEntry] = {
    REPRODUCIBILITY_ABOVE_CAP: CodeEntry(
        level="must_fix",
        actions=["enable_policy"],
        message=(
            "A patch exists at reproducibility level {reproducibility}, above this site's "
            "tool_patch_reproducibility, so it was not applied. Raise the cap to apply it."
        ),
    ),
    REQUIREMENT_CHANGES_DISABLED: CodeEntry(
        level="must_fix",
        actions=["enable_policy"],
        message=(
            "A patch exists but changes this tool's requirements, and this site sets "
            "tool_patch_requirement_changes to false, so it was not applied."
        ),
    ),
    REVISION_MISMATCH: CodeEntry(
        level="info",
        actions=["update_revision"],
        message=(
            "Installed content differs from the content this version's patch was written for, so the patch "
            "was not applied. Update the repository to the latest installable revision at this version."
        ),
    ),
}


class _Placeholders(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def render_message(template: str, **values: str | None) -> str:
    """Fill ``{fixed_in}``-style placeholders, leaving unknown or empty ones as written."""
    placeholders = _Placeholders({k: v for k, v in values.items() if v is not None})
    try:
        return Formatter().vformat(template, (), placeholders)
    except (ValueError, IndexError, AttributeError):
        return template
