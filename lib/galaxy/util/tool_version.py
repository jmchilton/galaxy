def remove_version_from_guid(guid: str) -> str | None:
    """
    Removes version from toolshed-derived tool_id(=guid).
    """
    if "/" not in guid:
        return None
    last_slash = guid.rfind("/")
    return guid[:last_slash]


def is_shed_guid(tool_id: str) -> bool:
    """
    True when ``tool_id`` is a toolshed-derived guid
    (``toolshed/repos/owner/name/tool_id/version``).
    """
    return "/repos/" in tool_id


def versionless_tool_id(tool_id: str) -> str:
    """
    Tool id without a Tool Shed version suffix; ids without one pass through unchanged.
    """
    if not is_shed_guid(tool_id):
        return tool_id
    # owner/repo/tool_id/version
    if len(tool_id.split("/repos/", 1)[1].split("/")) < 4:
        return tool_id
    return remove_version_from_guid(tool_id) or tool_id


def short_tool_id(guid: str) -> str:
    """
    Tool-id segment of a toolshed-derived tool_id(=guid),
    e.g. ``toolshed/repos/owner/name/tool_id/version`` -> ``tool_id``.
    Ids that aren't guids pass through unchanged.
    """
    versionless = remove_version_from_guid(guid)
    if not versionless or "/" not in versionless:
        return guid
    return versionless.rsplit("/", 1)[-1]
