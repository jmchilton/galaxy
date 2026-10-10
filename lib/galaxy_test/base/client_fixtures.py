"""Record real API responses as client test fixtures.

Fixtures are stored verbatim. Values that change on every run (encoded ids,
UUIDs, datetimes, the server's URL) are tolerated by :func:`compare` rather
than normalized away, so a regenerated fixture is only rewritten when it
changed meaningfully.
"""

import re
from collections.abc import (
    Iterable,
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from typing import Any

PathSegment = str | int
JsonPath = tuple[PathSegment, ...]

VOLATILE_TOKEN = re.compile(
    r"(?P<uuid>(?<![0-9A-Za-z])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9A-Za-z]))"
    r"|(?P<datetime>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
    r"|(?P<server>https?://(?:[^\s/:?#\"']+:\d+|localhost|127\.0\.0\.1))"
    r"|(?P<id>(?<![0-9A-Za-z])(?:[0-9a-f]{16})+(?![0-9A-Za-z]))"
)
# Tokens whose old -> new mapping must be one-to-one across the document. Encoded ids
# are only unique per table, so they're keyed by the entity they refer to (see _child_role).
REFERENCE_KINDS = ("uuid", "id")


@dataclass(frozen=True)
class Difference:
    path: str
    kind: str
    old: Any = None
    new: Any = None

    def __str__(self) -> str:
        return f"{self.path}: {self.kind} (old={self.old!r}, new={self.new!r})"


def format_path(path: JsonPath) -> str:
    parts = ["$"]
    for segment in path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", segment):
            parts.append(f".{segment}")
        else:
            parts.append(f'["{segment}"]')
    return "".join(parts)


def _path_pattern(pattern: str) -> re.Pattern:
    regex = (
        re.escape(pattern)
        .replace(r"\[\*\]", r"\[\d+\]")
        .replace(r"\.\*", r"(?:\.[A-Za-z_][A-Za-z0-9_]*|\[\"[^\"]*\"\])")
    )
    return re.compile(regex)


def _tokenize(value: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a string into a template with volatile tokens replaced, plus the tokens."""
    tokens: list[tuple[str, str]] = []

    def replace(match: re.Match) -> str:
        kind = match.lastgroup
        assert kind
        tokens.append((kind, match.group()))
        return f"<{kind}>"

    return VOLATILE_TOKEN.sub(replace, value), tokens


@dataclass
class _Comparison:
    volatile_paths: list[re.Pattern]
    open_paths: list[re.Pattern]
    differences: list[Difference] = field(default_factory=list)
    old_to_new: dict[tuple[str, str], str] = field(default_factory=dict)
    new_to_old: dict[tuple[str, str], str] = field(default_factory=dict)

    def matches(self, patterns: list[re.Pattern], path: JsonPath) -> bool:
        formatted = format_path(path)
        return any(p.fullmatch(formatted) for p in patterns)

    def differ(self, path: JsonPath, kind: str, old: Any = None, new: Any = None) -> None:
        self.differences.append(Difference(format_path(path), kind, old, new))

    def compare(self, path: JsonPath, old: Any, new: Any, role: str = "") -> None:
        if self.matches(self.volatile_paths, path):
            return
        old_type, new_type = _json_type(old), _json_type(new)
        if old_type != new_type:
            self.differ(path, "type", old, new)
        elif old_type == "object":
            self.compare_objects(path, old, new, role)
        elif old_type == "array":
            self.compare_arrays(path, old, new, role)
        elif old_type == "string":
            if not self.strings_match(path, old, new, role):
                self.differ(path, "value", old, new)
        elif old != new:
            self.differ(path, "value", old, new)

    def compare_objects(self, path: JsonPath, old: dict, new: dict, role: str) -> None:
        unmatched_new = [key for key in new if key not in old]
        pairs: list[tuple[str, str]] = []
        removed: list[str] = []
        for key in old:
            if key in new:
                pairs.append((key, key))
                continue
            # Keys that are themselves ids (e.g. outputs keyed by dataset id) pair by template.
            template, tokens = _tokenize(key)
            partner = next((k for k in unmatched_new if tokens and _tokenize(k)[0] == template), None)
            if partner is not None and self.strings_match(path + (key,), key, partner, role):
                unmatched_new.remove(partner)
                pairs.append((key, partner))
            else:
                removed.append(key)
        for old_key, new_key in pairs:
            self.compare(path + (old_key,), old[old_key], new[new_key], _child_role(old, old_key, role))
        for key in removed:
            self.differ(path + (key,), "removed", old[key], None)
        if not self.matches(self.open_paths, path):
            for key in unmatched_new:
                self.differ(path + (key,), "added", None, new[key])

    def compare_arrays(self, path: JsonPath, old: list, new: list, role: str) -> None:
        if len(old) != len(new):
            self.differ(path, "length", len(old), len(new))
            return
        for index, (old_item, new_item) in enumerate(zip(old, new)):
            self.compare(path + (index,), old_item, new_item, role)

    def strings_match(self, path: JsonPath, old: str, new: str, role: str) -> bool:
        old_template, old_tokens = _tokenize(old)
        new_template, new_tokens = _tokenize(new)
        if old_template != new_template:
            return False
        for (kind, old_token), (_, new_token) in zip(old_tokens, new_tokens):
            if kind in REFERENCE_KINDS and not self._reference_consistent(_scope(kind, role), old_token, new_token):
                self.differ(path, "id_mapping", old, new)
                return True
        self._record_references(role, old_tokens, new_tokens)
        return True

    def _reference_consistent(self, scope: str, old_token: str, new_token: str) -> bool:
        return self.old_to_new.get((scope, old_token), new_token) == new_token and (
            self.new_to_old.get((scope, new_token), old_token) == old_token
        )

    def _record_references(
        self, role: str, old_tokens: list[tuple[str, str]], new_tokens: list[tuple[str, str]]
    ) -> None:
        for (kind, old_token), (_, new_token) in zip(old_tokens, new_tokens):
            if kind in REFERENCE_KINDS:
                scope = _scope(kind, role)
                self.old_to_new.setdefault((scope, old_token), new_token)
                self.new_to_old.setdefault((scope, new_token), old_token)


def _scope(kind: str, role: str) -> str:
    # UUIDs are globally unique, so one mapping covers the whole document.
    return role if kind == "id" else kind


def _child_role(parent: dict, key: str, parent_role: str) -> str:
    """The entity an id under ``parent[key]`` refers to.

    ``history_id`` and ``history_ids`` refer to ``history``, as does ``id`` beside
    ``model_class: History``. Any other ``id`` takes the role of the object holding it,
    and anything else the key's own name.
    """
    for suffix in ("_ids", "_id"):
        if key.endswith(suffix) and len(key) > len(suffix):
            return key[: -len(suffix)]
    if key == "id":
        model_class = parent.get("model_class")
        if isinstance(model_class, str):
            return re.sub(r"(?<!^)(?=[A-Z])", "_", model_class).lower()
        return parent_role
    return key


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    raise TypeError(f"Not a JSON value: {value!r}")


def compare(
    old: Any,
    new: Any,
    volatile_paths: Iterable[str] = (),
    open_paths: Iterable[str] = (),
) -> Sequence[Difference]:
    """Return the meaningful differences between a committed fixture and a new capture.

    ``volatile_paths`` are JSON paths (``$.jobs[*].runtime``) whose values may change freely.
    ``open_paths`` are objects that may gain keys, such as ``/api/configuration``.
    """
    comparison = _Comparison(
        volatile_paths=[_path_pattern(p) for p in volatile_paths],
        open_paths=[_path_pattern(p) for p in open_paths],
    )
    comparison.compare((), old, new)
    return comparison.differences
