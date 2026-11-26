"""Galaxy-side wiring of :mod:`galaxy.tool_util.patches`: config to database, and tool patch helpers."""

import os
import threading
import weakref
from typing import (
    cast,
    TYPE_CHECKING,
)

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.patches import (
    key_from_ids,
    load_tool_patch_database,
    ToolPatchDatabase,
    ToolPatchInfo,
)
from galaxy.tool_util.patches.engine import APPLIED
from galaxy.tool_util.patches.model import (
    level_index,
    ReproducibilityLevel,
)
from galaxy.util.path import StrPath
from galaxy.version import VERSION_MAJOR

if TYPE_CHECKING:
    from galaxy.config import GalaxyAppConfiguration
    from galaxy.tools.source_store.index import ToolIndexEntry

# Job-cache reuse across the patched/unpatched boundary is safe only up to this level.
JOB_CACHE_SAFE_LEVEL: ReproducibilityLevel = "rejects_inputs"


# (paths, reproducibility, requirement_changes)
_Settings = tuple[tuple[str, ...], ReproducibilityLevel, bool]

# Keyed by config object, then settings; weak so configs stay picklable and collectable.
_databases: "weakref.WeakKeyDictionary[GalaxyAppConfiguration, dict[_Settings, ToolPatchDatabase]]" = (
    weakref.WeakKeyDictionary()
)
_databases_lock = threading.Lock()


def tool_patch_database_from_config(config: "GalaxyAppConfiguration") -> ToolPatchDatabase | None:
    """The configured patch database, or None when ``tool_patch_paths`` is empty.

    Loaded once per config object and settings, so collection changes need a restart.
    """
    paths = tuple(config.tool_patch_paths or ())
    if not paths:
        return None
    reproducibility = cast(ReproducibilityLevel, config.tool_patch_reproducibility)
    requirement_changes = bool(config.tool_patch_requirement_changes)
    settings: _Settings = (paths, reproducibility, requirement_changes)
    with _databases_lock:
        databases = _databases.setdefault(config, {})
        if settings not in databases:
            databases[settings] = load_tool_patch_database(
                list(paths),
                reproducibility=reproducibility,
                requirement_changes=requirement_changes,
                galaxy_series=VERSION_MAJOR,
            )
        return databases[settings]


def apply_tool_patches(
    db: ToolPatchDatabase | None, tool_source: ToolSource, guid: str | None, config_file: StrPath | None
) -> ToolSource:
    """Patch a freshly parsed tool source; returns ``tool_source`` itself without a database."""
    if db is None:
        return tool_source
    return db.apply_patches(tool_source, guid=guid, tool_path=os.fspath(config_file) if config_file else None)


def indexed_patch_is_current(db: ToolPatchDatabase | None, entry: "ToolIndexEntry", config_file: StrPath) -> bool:
    """True when ``entry`` records the patch digest :func:`apply_tool_patches` would record now, without parsing."""
    recorded = entry.patch.digest if entry.patch else None
    current = None
    if db is not None and entry.source_class == "XmlToolSource":
        key = key_from_ids(entry.id, entry.id, entry.version)
        current = db.tool_digest(key, os.fspath(config_file)) if key is not None else None
    return recorded == current


def patch_blocks_job_cache(patch: ToolPatchInfo | None) -> bool:
    """True when an applied patch may change previously successful jobs' outputs."""
    if patch is None:
        return False
    safe = level_index(JOB_CACHE_SAFE_LEVEL)
    return any(
        state.state == APPLIED and state.reproducibility is not None and level_index(state.reproducibility) > safe
        for state in patch.states
    )
