"""Declarative patches for installed tool versions, applied to the macro-expanded XML."""

from .collection import (
    CollectionError,
    PatchCollection,
)
from .database import (
    BUILTIN,
    load_tool_patch_database,
    ToolPatchDatabase,
)
from .keys import (
    key_from_ids,
    patch_key,
    PatchKey,
)
from .model import (
    AdvisoryInfo,
    patches_as_dicts,
    PatchFile,
    PatchPolicy,
    PatchState,
    ToolPatchCollectionsSummary,
    ToolPatchInfo,
)

__all__ = (
    "AdvisoryInfo",
    "BUILTIN",
    "CollectionError",
    "key_from_ids",
    "load_tool_patch_database",
    "patch_key",
    "PatchCollection",
    "PatchFile",
    "PatchKey",
    "patches_as_dicts",
    "PatchPolicy",
    "PatchState",
    "ToolPatchCollectionsSummary",
    "ToolPatchDatabase",
    "ToolPatchInfo",
)
