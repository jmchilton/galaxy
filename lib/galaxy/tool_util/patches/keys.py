"""Patch keys and Go module-cache style path segment encoding."""

from galaxy.tool_util.parser.interface import ToolSource

LOCAL = "_local"
PatchKey = tuple[str, ...]

_SAFE_BYTES = frozenset(b"abcdefghijklmnopqrstuvwxyz0123456789._+-")
_UPPER_HEX = frozenset("0123456789ABCDEF")


def encode_segment(raw: str) -> str:
    """Uppercase becomes ``!`` plus lowercase; bytes outside ``[a-z0-9._+-]`` become ``%XX``."""
    out = []
    for ch in raw:
        if "A" <= ch <= "Z":
            out.append("!" + ch.lower())
            continue
        for byte in ch.encode("utf-8"):
            out.append(chr(byte) if byte in _SAFE_BYTES else f"%{byte:02X}")
    return "".join(out)


def decode_segment(encoded: str) -> str:
    """Inverse of :func:`encode_segment`; raises ValueError on malformed input."""
    buf = bytearray()
    i = 0
    while i < len(encoded):
        ch = encoded[i]
        if ch == "!":
            nxt = encoded[i + 1 : i + 2]
            if not ("a" <= nxt <= "z" and len(nxt) == 1):
                raise ValueError(f"bad escape in {encoded!r}")
            buf += nxt.upper().encode("ascii")
            i += 2
        elif ch == "%":
            hex_digits = encoded[i + 1 : i + 3]
            if len(hex_digits) != 2 or not set(hex_digits) <= _UPPER_HEX:
                raise ValueError(f"bad percent escape in {encoded!r}")
            buf.append(int(hex_digits, 16))
            i += 3
        elif len(ch) == 1 and ord(ch) < 128 and ord(ch) in _SAFE_BYTES:
            buf.append(ord(ch))
            i += 1
        else:
            raise ValueError(f"unencoded character {ch!r} in {encoded!r}")
    return buf.decode("utf-8")


def is_canonical_segment(encoded: str) -> bool:
    if encoded in ("", ".", ".."):
        return False
    try:
        return encode_segment(decode_segment(encoded)) == encoded
    except (ValueError, UnicodeDecodeError):
        return False


def is_shed_key(key: PatchKey) -> bool:
    return key[0] != LOCAL


def key_string(key: PatchKey) -> str:
    return "/".join(key)


def _is_shed_guid(guid: str | None) -> bool:
    return bool(guid) and "/repos/" in str(guid)


def key_from_ids(guid: str | None, tool_id: str | None, version: str | None) -> PatchKey | None:
    """``(owner, repo, tool_id, version)`` from a shed guid, else ``(_local, tool_id, version)``."""
    if guid and _is_shed_guid(guid):
        parts = guid.split("/repos/", 1)[1].split("/")
        if len(parts) != 4 or not all(parts):
            return None
        return tuple(parts)
    if not tool_id or not version:
        return None
    return (LOCAL, tool_id, version)


def patch_key(tool_source: ToolSource, guid: str | None = None) -> PatchKey | None:
    """Key for a tool source; the XML id and version are read only for non-shed tools."""
    if _is_shed_guid(guid):
        return key_from_ids(guid, None, None)
    return key_from_ids(None, tool_source.parse_id(), tool_source.parse_version())
