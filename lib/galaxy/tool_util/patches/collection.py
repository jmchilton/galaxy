"""A patch collection directory: path-keyed index, lazy parsing, digests and codes."""

import hashlib
import logging
import os
import re
import stat
import threading
from dataclasses import dataclass
from typing import Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictInt,
    StrictStr,
    ValidationError,
)

from .keys import (
    decode_segment,
    is_canonical_segment,
    is_shed_key,
    LOCAL,
    PatchKey,
)
from .model import (
    CodeEntry,
    CodesFile,
    PatchFile,
)

log = logging.getLogger(__name__)

FORMAT_VERSION = 1
PATCH_SUFFIX = ".yml"
REFUSED_LOCAL_PREFIXES = ("CONVERTER_", "__")
_OVERRIDE_NAME = re.compile(r"^@([0-9a-f]{12}|[0-9a-f]{40})\.yml$")


class CollectionError(Exception):
    """The collection can't be used at all."""


class CollectionMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: StrictStr
    version: str
    format_version: StrictInt


@dataclass(frozen=True)
class LoadedPatch:
    patch: PatchFile
    path: str
    sha256: str


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe loader that rejects duplicate mapping keys, which plain YAML silently collapses."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def parse_patch_yaml(data: bytes) -> Any:
    return yaml.load(data, Loader=_UniqueKeyLoader)


def _read_yaml(path: str) -> Any:
    with open(path, "rb") as f:
        return yaml.load(f, Loader=_UniqueKeyLoader)


def _file_sha256(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


class PatchCollection:
    """Patch files under ``<root>/patches``, indexed by key without parsing them."""

    def __init__(self, root: str) -> None:
        self.root = os.path.realpath(root)
        if not os.path.isdir(self.root):
            raise CollectionError(f"{root} is not a directory")
        try:
            raw = _read_yaml(os.path.join(self.root, "collection.yml"))
        except (OSError, yaml.YAMLError) as e:
            raise CollectionError(f"can't read collection.yml: {e}")
        if not isinstance(raw, dict) or raw.get("format_version") != FORMAT_VERSION:
            found = raw.get("format_version") if isinstance(raw, dict) else None
            raise CollectionError(f"unsupported format_version {found!r} (this Galaxy reads {FORMAT_VERSION})")
        try:
            metadata = CollectionMetadata.model_validate({**raw, "version": str(raw.get("version", ""))})
        except ValidationError as e:
            raise CollectionError(f"invalid collection.yml: {e}")
        self.name = metadata.name
        self.version = metadata.version
        self._codes = self._load_codes()
        # Advisory levels and file validity depend on codes.yml, so digests fold it in.
        self.codes_sha256 = _file_sha256(os.path.join(self.root, "codes.yml")) or ""
        self._files: dict[PatchKey, str] = {}
        self._overrides: dict[PatchKey, dict[str, str]] = {}
        self._resolved: dict[str, str] = {}
        self._lock = threading.Lock()
        self._sha256: dict[str, str | None] = {}
        self._loaded: dict[str, LoadedPatch | None] = {}
        self._digest: str | None = None
        self._walk()

    def __repr__(self) -> str:
        return f"PatchCollection({self.name!r}, {self.version!r}, {self.root!r})"

    def _load_codes(self) -> dict[str, CodeEntry] | None:
        path = os.path.join(self.root, "codes.yml")
        if not os.path.exists(path):
            return None
        try:
            return CodesFile.model_validate(_read_yaml(path)).codes
        except (OSError, yaml.YAMLError, ValidationError) as e:
            raise CollectionError(f"invalid codes.yml: {e}")

    # --- walk ---

    def _refuse(self, path: str, reason: str) -> None:
        log.error("tool patches: %s: refusing %s: %s", self.name, os.path.relpath(path, self.root), reason)

    def _decode(self, entry: os.DirEntry[str], name: str | None = None) -> str | None:
        segment = entry.name if name is None else name
        if not is_canonical_segment(segment):
            self._refuse(entry.path, f"{segment!r} is not a canonical encoded segment")
            return None
        return decode_segment(segment)

    def _dirs(self, path: str) -> list[os.DirEntry[str]]:
        out = []
        with os.scandir(path) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.is_dir(follow_symlinks=False):
                    out.append(entry)
                elif entry.is_symlink() and entry.is_dir():
                    self._refuse(entry.path, "directory symlinks are not followed")
                elif entry.name.endswith(PATCH_SUFFIX):
                    self._refuse(entry.path, "patch file at the wrong depth")
        return out

    def _files_in(self, path: str) -> list[os.DirEntry[str]]:
        with os.scandir(path) as entries:
            return sorted(entries, key=lambda e: e.name)

    def _register(self, entry: os.DirEntry[str]) -> str | None:
        """Relative path of a patch file whose resolved target is a regular file inside the root."""
        resolved = os.path.realpath(entry.path)
        if os.path.commonpath([resolved, self.root]) != self.root:
            self._refuse(entry.path, "it resolves outside the collection")
            return None
        try:
            if not stat.S_ISREG(os.stat(resolved).st_mode):
                self._refuse(entry.path, "it is not a regular file")
                return None
        except OSError as e:
            self._refuse(entry.path, str(e))
            return None
        rel = os.path.relpath(entry.path, self.root).replace(os.sep, "/")
        self._resolved[rel] = resolved
        return rel

    def _add_version_file(self, prefix: PatchKey, entry: os.DirEntry[str]) -> None:
        if not entry.name.endswith(PATCH_SUFFIX):
            log.debug("tool patches: ignoring %s", entry.path)
            return
        version = self._decode(entry, entry.name[: -len(PATCH_SUFFIX)])
        if version is not None and (rel := self._register(entry)):
            self._files[(*prefix, version)] = rel

    def _add_overrides(self, key: PatchKey, directory: os.DirEntry[str]) -> None:
        for entry in self._files_in(directory.path):
            match = _OVERRIDE_NAME.match(entry.name)
            if not match:
                if entry.name.endswith(PATCH_SUFFIX) or entry.is_dir(follow_symlinks=False):
                    self._refuse(entry.path, "override names are @<12 or 40 hex digits>.yml")
                continue
            if rel := self._register(entry):
                self._overrides.setdefault(key, {})[match.group(1)] = rel

    def _walk(self) -> None:
        patches = os.path.join(self.root, "patches")
        if not os.path.isdir(patches):
            return
        for owner in self._dirs(patches):
            if owner.name == LOCAL:
                self._walk_local(owner)
            elif (owner_name := self._decode(owner)) is not None:
                self._walk_shed_owner(owner_name, owner)

    def _walk_local(self, owner: os.DirEntry[str]) -> None:
        for tool in self._dirs(owner.path):
            tool_id = self._decode(tool)
            if tool_id is None:
                continue
            if tool_id.startswith(REFUSED_LOCAL_PREFIXES):
                self._refuse(tool.path, "Galaxy-bundled tools never get patch keys")
                continue
            self._walk_tool((LOCAL, tool_id), tool)

    def _walk_shed_owner(self, owner_name: str, owner: os.DirEntry[str]) -> None:
        for repo in self._dirs(owner.path):
            repo_name = self._decode(repo)
            if repo_name is None:
                continue
            for tool in self._dirs(repo.path):
                tool_id = self._decode(tool)
                if tool_id is not None:
                    self._walk_tool((owner_name, repo_name, tool_id), tool)

    def _walk_tool(self, prefix: PatchKey, tool: os.DirEntry[str]) -> None:
        """Version files of one tool, plus per-changeset override directories for shed keys."""
        for entry in self._files_in(tool.path):
            if not entry.is_dir(follow_symlinks=False):
                self._add_version_file(prefix, entry)
            elif not is_shed_key(prefix):
                self._refuse(entry.path, "per-changeset overrides need a Tool Shed key")
            elif (version := self._decode(entry)) is not None:
                self._add_overrides((*prefix, version), entry)

    # --- lookup ---

    @property
    def has_patches(self) -> bool:
        return bool(self._files or self._overrides)

    def has_key(self, key: PatchKey) -> bool:
        return key in self._files or key in self._overrides

    def version_file(self, key: PatchKey) -> str | None:
        return self._files.get(key)

    def has_overrides(self, key: PatchKey) -> bool:
        return key in self._overrides

    def override_for(self, key: PatchKey, node: str | None) -> str | None:
        """Override whose changeset is the longest prefix of the full hex node."""
        overrides = self._overrides.get(key)
        if not overrides or not node:
            return None
        matches = [cs for cs in overrides if node.startswith(cs)]
        return overrides[max(matches, key=len)] if matches else None

    def paths(self) -> list[str]:
        return sorted(self._resolved)

    # --- content ---

    def _read(self, rel: str) -> bytes | None:
        try:
            with open(self._resolved[rel], "rb") as f:
                return f.read()
        except OSError as e:
            log.error("tool patches: %s: can't read %s: %s", self.name, rel, e)
            return None

    def file_sha256(self, rel: str) -> str | None:
        with self._lock:
            if rel not in self._sha256:
                data = self._read(rel)
                self._sha256[rel] = hashlib.sha256(data).hexdigest() if data is not None else None
            return self._sha256[rel]

    def load(self, rel: str) -> LoadedPatch | None:
        """Parse a patch file once; None (logged) when it is invalid."""
        with self._lock:
            if rel not in self._loaded:
                self._loaded[rel] = self._parse(rel)
            return self._loaded[rel]

    def _parse(self, rel: str) -> LoadedPatch | None:
        data = self._read(rel)
        if data is None:
            return None
        sha256 = hashlib.sha256(data).hexdigest()
        if self._sha256.setdefault(rel, sha256) != sha256:
            log.error("tool patches: %s: %s changed after it was hashed, skipped", self.name, rel)
            return None
        try:
            patch = PatchFile.model_validate(parse_patch_yaml(data))
            self._check_codes(patch)
            if patch.advisory and patch.advisory.expanded_sha256 and not os.path.basename(rel).startswith("@"):
                raise ValueError("expanded_sha256 is only for per-changeset overrides")
        except (yaml.YAMLError, ValidationError, ValueError) as e:
            log.error("tool patches: %s: %s is invalid, skipped: %s", self.name, rel, e)
            return None
        return LoadedPatch(patch=patch, path=rel, sha256=sha256)

    def _check_codes(self, patch: PatchFile) -> None:
        if self._codes is None or patch.advisory is None:
            return
        entry = self._codes.get(patch.advisory.code)
        if entry is None:
            raise ValueError(f"unknown advisory code {patch.advisory.code!r}")
        if patch.advisory.action not in entry.actions:
            raise ValueError(f"code {patch.advisory.code!r} doesn't allow action {patch.advisory.action!r}")

    def code(self, code: str) -> CodeEntry | None:
        return self._codes.get(code) if self._codes else None

    @property
    def digest(self) -> str:
        """sha256 over every patch file (path, NUL, resolved content sha256) and ``codes.yml``."""
        if self._digest is None:
            h = hashlib.sha256()
            for rel in self.paths():
                sha256 = self.file_sha256(rel)
                h.update(rel.encode("utf-8") + b"\0" + (bytes.fromhex(sha256) if sha256 else b""))
            h.update(b"\0codes.yml\0" + self.codes_sha256.encode("ascii"))
            self._digest = h.hexdigest()
        return self._digest
