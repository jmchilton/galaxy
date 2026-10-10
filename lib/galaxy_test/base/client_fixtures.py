"""Record real API responses as client test fixtures.

Fixtures are stored verbatim. Values that change on every run (encoded ids,
UUIDs, datetimes, the server's URL) are tolerated by :func:`compare` rather
than normalized away, so a regenerated fixture is only rewritten when it
changed meaningfully.

``GALAXY_TEST_CLIENT_FIXTURES`` selects what a capture does with a response:

- unset: write to a temp dir and leave committed fixtures alone.
- ``update``: rewrite fixtures that changed meaningfully and print the differences.
- ``rebuild``: rewrite every fixture.
- ``check``: fail on any meaningful change or missing fixture.

Fixtures are written to ``client/src/api/__fixtures__`` unless
``GALAXY_TEST_CLIENT_FIXTURES_DIR`` names another directory.
"""

import json
import os
import re
import string
import tempfile
from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from pathlib import Path
from typing import (
    Any,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from galaxy_test.base.api import ApiTestInteractor

MODE_ENV = "GALAXY_TEST_CLIENT_FIXTURES"
DIR_ENV = "GALAXY_TEST_CLIENT_FIXTURES_DIR"
MODES = (None, "update", "rebuild", "check")
METHODS = ("get", "put", "post", "delete", "patch")
CLIENT_DIR = Path(__file__).resolve().parents[3] / "client"
SCENARIO = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")

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


CompareFn = Callable[..., Sequence[Difference]]


def fixture_relative_path(path_template: str, method: str, scenario: str, status: int = 200) -> str:
    """Name a fixture after its OpenAPI path and method, e.g. ``api/histories/{history_id}/get.default.json``."""
    method = method.lower()
    if method not in METHODS:
        raise ValueError(f"Unknown HTTP method {method!r}")
    if not path_template.startswith("/"):
        raise ValueError(f"Expected an OpenAPI path starting with '/', got {path_template!r}")
    if not SCENARIO.fullmatch(scenario):
        raise ValueError(f"Scenario {scenario!r} must be lower_snake_case")
    status_part = "" if 200 <= status < 300 else f".{status}"
    return f"{path_template.strip('/')}/{method}{status_part}.{scenario}.json"


def format_api_path(path_template: str, path_params: dict[str, str]) -> str:
    names = {name for _, name, _, _ in string.Formatter().parse(path_template) if name}
    if missing := names - path_params.keys():
        raise ValueError(f"Missing path parameters {sorted(missing)} for {path_template}")
    if extra := path_params.keys() - names:
        raise ValueError(f"Unknown path parameters {sorted(extra)} for {path_template}")
    return path_template.format(**path_params)


def resolve_fixture_dir(mode: str | None, explicit_dir: str | None, client_dir: Path = CLIENT_DIR) -> Path:
    if mode is None:
        return Path(tempfile.mkdtemp(prefix="galaxy_client_fixtures_"))
    if explicit_dir:
        return Path(explicit_dir)
    if not client_dir.is_dir():
        raise Exception(f"{MODE_ENV}={mode} needs {DIR_ENV} when Galaxy's client/ directory is absent")
    return client_dir / "src" / "api" / "__fixtures__"


def write_fixture(
    mode: str | None,
    fixture_dir: Path,
    relative_path: str,
    response: Any,
    volatile_paths: Iterable[str] = (),
    open_paths: Iterable[str] = (),
    compare_fn: CompareFn = compare,
) -> str:
    """Apply ``mode`` to a captured response; return ``"written"`` or ``"unchanged"``."""
    if mode not in MODES:
        raise ValueError(f"{MODE_ENV} must be one of update, rebuild or check, got {mode!r}")
    target = fixture_dir / relative_path
    if mode in ("update", "check") and target.exists():
        committed = json.loads(target.read_text())
        differences = compare_fn(committed, response, volatile_paths=volatile_paths, open_paths=open_paths)
        if not differences:
            return "unchanged"
        report = "\n".join(f"  {difference}" for difference in differences)
        if mode == "check":
            raise AssertionError(
                f"{relative_path} differs from the server response; rerun with {MODE_ENV}=update\n{report}"
            )
        print(f"Updating client fixture {relative_path}:\n{report}")
    elif mode == "check":
        raise AssertionError(f"Missing client fixture {relative_path}; rerun with {MODE_ENV}=update")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(response, indent=2, ensure_ascii=False) + "\n")
    return "written"


class ClientFixtures:
    """Capture API responses as client fixtures from an API or integration test."""

    def __init__(
        self, galaxy_interactor: "ApiTestInteractor", mode: str | None = None, fixture_dir: Path | None = None
    ):
        self.galaxy_interactor = galaxy_interactor
        self.mode = mode if mode is not None else (os.environ.get(MODE_ENV) or None)
        self.fixture_dir = fixture_dir or resolve_fixture_dir(self.mode, os.environ.get(DIR_ENV))

    def capture(
        self,
        method: str,
        path_template: str,
        scenario: str,
        *,
        purpose: Callable[[Any], object],
        status: int = 200,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        volatile_paths: Iterable[str] = (),
        open_paths: Iterable[str] = (),
        **path_params: str,
    ) -> Any:
        """Request ``path_template`` and record the response.

        ``purpose`` asserts what the fixture exists to show (e.g. ``state == "error"``),
        and runs before anything is written.
        """
        relative_path = fixture_relative_path(path_template, method, scenario, status)
        path = format_api_path(path_template, path_params)
        request = getattr(self.galaxy_interactor, method.lower())
        if method.lower() == "get":
            response = request(path, data=params)
        else:
            response = request(path, data=body, json=True)
        assert (
            response.status_code == status
        ), f"{method.upper()} {path} returned {response.status_code}, expected {status}: {response.text}"
        response_json = response.json()
        purpose(response_json)
        write_fixture(self.mode, self.fixture_dir, relative_path, response_json, volatile_paths, open_paths)
        return response_json
