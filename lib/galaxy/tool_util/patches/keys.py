"""Patch keys; each key segment is a path segment of the collection, stored verbatim."""

from galaxy.tool_util.parser.interface import ToolSource
from galaxy.util.tool_version import is_shed_guid

LOCAL = "_local"
PatchKey = tuple[str, ...]


def is_valid_segment(name: str) -> bool:
    """A directory or file name that can be a key segment: non-empty and not hidden (so never ``.`` or ``..``)."""
    return bool(name) and not name.startswith(".")


def is_shed_key(key: PatchKey) -> bool:
    return key[0] != LOCAL


def key_string(key: PatchKey) -> str:
    return "/".join(key)


def key_from_ids(guid: str | None, tool_id: str | None, version: str | None) -> PatchKey | None:
    """``(owner, repo, tool_id, version)`` from a shed guid, else ``(_local, tool_id, version)``."""
    if guid and is_shed_guid(guid):
        parts = guid.split("/repos/", 1)[1].split("/")
        if len(parts) != 4 or not all(parts):
            return None
        return tuple(parts)
    if not tool_id or not version:
        return None
    return (LOCAL, tool_id, version)


def patch_key(tool_source: ToolSource, guid: str | None = None) -> PatchKey | None:
    """Key for a tool source; the XML id and version are read only for non-shed tools."""
    if guid and is_shed_guid(guid):
        return key_from_ids(guid, None, None)
    return key_from_ids(None, tool_source.parse_id(), tool_source.parse_version())
