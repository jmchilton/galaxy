"""Galaxy-side wiring of :mod:`galaxy.tool_util.patches`: config to database, and tool patch helpers."""

import os
from typing import (
    Any,
    cast,
    TYPE_CHECKING,
)

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import (
    load_tool_patch_database,
    ToolPatchDatabase,
    ToolPatchInfo,
)
from galaxy.tool_util.patches.model import (
    level_index,
    ReproducibilityLevel,
)
from galaxy.version import VERSION_MAJOR

if TYPE_CHECKING:
    from galaxy.config import GalaxyAppConfiguration

# Job-cache reuse across the patched/unpatched boundary is safe only up to this level.
JOB_CACHE_SAFE_LEVEL: ReproducibilityLevel = "rejects_inputs"


def tool_patch_database_from_config(config: "GalaxyAppConfiguration") -> ToolPatchDatabase | None:
    """The configured patch database, or None when ``tool_patch_paths`` is empty."""
    paths = list(getattr(config, "tool_patch_paths", None) or [])
    if not paths:
        return None
    return load_tool_patch_database(
        paths,
        reproducibility=cast(ReproducibilityLevel, config.tool_patch_reproducibility),
        requirement_changes=config.tool_patch_requirement_changes,
        galaxy_series=VERSION_MAJOR,
    )


def apply_tool_patches(
    db: ToolPatchDatabase | None, tool_source: ToolSource, guid: str | None, config_file: Any
) -> ToolSource:
    """Patch a freshly parsed tool source; returns ``tool_source`` itself without a database."""
    if db is None:
        return tool_source
    hint = os.path.dirname(os.path.abspath(str(config_file))) if config_file else None
    return db.apply_patches(tool_source, guid=guid, repository_dir_hint=hint)


def patches_as_dicts(patch: ToolPatchInfo | None) -> list[dict[str, Any]] | None:
    """API form of a tool's patch states, or None for an unpatched tool."""
    if patch is None or not patch.states:
        return None
    return [state.model_dump(mode="json") for state in patch.states]


def patch_blocks_job_cache(patch: ToolPatchInfo | None) -> bool:
    """True when an applied patch may change previously successful jobs' outputs."""
    if patch is None:
        return False
    safe = level_index(JOB_CACHE_SAFE_LEVEL)
    return any(
        state.state == "applied" and state.reproducibility is not None and level_index(state.reproducibility) > safe
        for state in patch.states
    )
