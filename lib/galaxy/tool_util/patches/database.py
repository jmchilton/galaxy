"""Stack patch collections and apply them to tool sources under a site policy."""

import hashlib
import logging
import os
import re
import threading
from collections import Counter
from collections.abc import (
    Callable,
    Sequence,
)
from dataclasses import (
    dataclass,
    field,
)
from functools import partial
from typing import (
    Any,
    Final,
    get_args,
)

from galaxy.tool_util.parser.factory import get_tool_source
from galaxy.tool_util.parser.interface import ToolSource
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.util import (
    ElementTree,
    xml_to_string,
)
from .codes import (
    GENERATED_CODES,
    render_message,
    REPRODUCIBILITY_ABOVE_CAP,
    REQUIREMENT_CHANGES_DISABLED,
    REVISION_MISMATCH,
)
from .collection import (
    CollectionError,
    PatchCollection,
)
from .engine import (
    ALREADY_APPLIED,
    APPLIED,
    evaluate_unit,
    MISMATCH,
    PatchUnit,
    plan_units,
    SKIPPED,
)
from .hg import (
    find_repository_dir,
    read_working_parent,
)
from .keys import (
    is_shed_key,
    key_string,
    patch_key,
    PatchKey,
)
from .model import (
    AdvisoryInfo,
    ChangeKind,
    CollectionRef,
    CollectionSummary,
    level_index,
    NEEDED_FROM_PATTERN,
    op_touches_requirements,
    PatchFile,
    PatchPolicy,
    PatchState,
    PatchStateName,
    PYTHON2TO3,
    ReproducibilityLevel,
    SECURITY,
    ToolPatchCollectionsSummary,
    ToolPatchInfo,
    Vulnerable,
)

log = logging.getLogger(__name__)

# Bump when the engine's results change for unchanged patch files, so stored patched sources re-patch.
ENGINE_VERSION = 1

BUILTIN = "builtin"
BUILTIN_COLLECTION_DIR = os.path.join(os.path.dirname(__file__), "builtin")
ADVISORY: Final = "advisory"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tree_text(tree: ElementTree) -> str:
    return str(xml_to_string(tree.getroot()))


def _dirstate_signature(repo_dir: str) -> tuple[int, int, int] | None:
    """Changes when hg rewrites the dirstate (e.g. ``hg update`` after a shed update)."""
    try:
        st = os.stat(os.path.join(repo_dir, ".hg", "dirstate"))
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


@dataclass
class _Input:
    """The tree one collection file sees, with its expanded sha256 computed on demand."""

    tree: ElementTree
    text: Callable[[], str]
    _sha256: str | None = field(default=None, init=False)

    def sha256(self) -> str:
        if self._sha256 is None:
            self._sha256 = _sha256(self.text())
        return self._sha256


@dataclass
class _FileResult:
    states: list[PatchState]
    tree: ElementTree | None


class ToolPatchDatabase:
    """Ordered patch collections plus the site policy and the running Galaxy release series."""

    def __init__(
        self,
        collections: Sequence[PatchCollection],
        policy: PatchPolicy | None = None,
        galaxy_series: str | None = None,
    ) -> None:
        if galaxy_series is not None and not re.match(NEEDED_FROM_PATTERN, galaxy_series):
            raise ValueError(f"galaxy_series must be a release series like '26.1', not {galaxy_series!r}")
        self.collections = list(collections)
        self.policy = policy or PatchPolicy()
        self.galaxy_series = galaxy_series
        self._active = [c for c in self.collections if c.has_patches]
        self._changesets: dict[str, tuple[tuple[int, int, int] | None, str | None]] = {}
        self._changeset_lock = threading.Lock()
        self._state_counts: Counter[str] = Counter()
        self._counts_lock = threading.Lock()

    # --- digests and summaries ---

    def _policy_bytes(self) -> bytes:
        parts = (ENGINE_VERSION, self.policy.reproducibility, self.policy.requirement_changes, self.galaxy_series or "")
        return "\0".join(map(str, parts)).encode()

    def digest_for(self, key: PatchKey, changeset: str | None = None) -> str | None:
        """sha256 over the files matched for key, their codes, the policy and series; None on a miss."""
        h = hashlib.sha256()
        matched = override_used = False
        for c in self._active:
            override = c.override_for(key, changeset)
            rels = [rel for rel in (override, c.version_file(key)) if rel is not None]
            if not rels:
                continue
            matched = True
            for rel in rels:
                h.update(f"{c.name}\0{rel}\0{c.file_sha256(rel) or ''}\0".encode())
            h.update(f"{c.codes_sha256}\0".encode())
            override_used = override_used or override is not None
        if not matched:
            return None
        h.update(self._policy_bytes())
        if override_used and changeset:
            h.update(b"\0" + changeset.encode("ascii"))
        return h.hexdigest()

    def collections_summary(self) -> ToolPatchCollectionsSummary:
        return ToolPatchCollectionsSummary(
            collections=[CollectionSummary(name=c.name, version=c.version, digest=c.digest) for c in self.collections],
            policy=self.policy,
            galaxy_series=self.galaxy_series,
        )

    def token(self) -> str:
        """Changes whenever any collection's content, the policy, the series or the engine version changes."""
        return _sha256(f"{ENGINE_VERSION}\0" + self.collections_summary().model_dump_json())

    # --- applying ---

    def changeset_for(self, key: PatchKey, tool_path: str | None) -> str | None:
        """Checked-out changeset of the repository holding tool_path (a file or directory) when an override could apply."""
        if not is_shed_key(key) or not any(c.has_overrides(key) for c in self._active):
            return None
        return self._checked_out_changeset(tool_path)

    def tool_digest(self, key: PatchKey, tool_path: str | None = None) -> str | None:
        """The digest :meth:`apply_patches` records for key, computed without parsing the tool."""
        return self.digest_for(key, self.changeset_for(key, tool_path))

    def apply_patches(
        self, tool_source: ToolSource, guid: str | None = None, tool_path: str | None = None
    ) -> ToolSource:
        """Patched source (or ``tool_source`` itself when no op applied), with ``patch_state`` set on any match."""
        if not self._active or not isinstance(tool_source, XmlToolSource):
            return tool_source
        key = patch_key(tool_source, guid)
        if key is None:
            return tool_source
        matching = [c for c in self._active if c.has_key(key)]
        if not matching:
            return tool_source
        changeset = self.changeset_for(key, tool_path or tool_source.source_path)
        current = _Input(tree=tool_source.xml_tree, text=tool_source.to_string)
        states: list[PatchState] = []
        for c in matching:
            result = self._apply_collection(c, key, changeset, current)
            states.extend(result.states)
            if result.tree is not None:
                current = _Input(tree=result.tree, text=partial(_tree_text, result.tree))
        info = ToolPatchInfo(digest=self.digest_for(key, changeset), states=states)
        patched: ToolSource = tool_source
        if current.tree is not tool_source.xml_tree:
            patched = get_tool_source(
                xml_tree=current.tree, config_file=tool_source.source_path, macro_paths=tool_source.macro_paths
            )
        patched.patch_state = info
        with self._counts_lock:
            self._state_counts.update(state.state for state in states)
        for state in states:
            _log_state(state)
        return patched

    def state_counts(self) -> Counter[str]:
        """Patch states this database has reported so far in this process."""
        with self._counts_lock:
            return Counter(self._state_counts)

    def summary(self, since: Counter[str] | None = None) -> str:
        """One line naming the collections and counting the patch states reported (after ``since``)."""
        collections = ", ".join(f"{c.name} {c.version} digest {c.digest[:12]}" for c in self.collections) or "none"
        counts = self.state_counts()
        counts.subtract(since or Counter())
        tally = ", ".join(f"{name} {counts[name]}" for name in get_args(PatchStateName))
        return f"tool patches: {collections}; {tally}"

    def _checked_out_changeset(self, start: str | None) -> str | None:
        if not start:
            return None
        repo_dir = find_repository_dir(start if os.path.isdir(start) else os.path.dirname(start))
        if repo_dir is None:
            log.debug("tool patches: no Mercurial repository above %s, using version files", start)
            return None
        signature = _dirstate_signature(repo_dir)
        with self._changeset_lock:
            cached = self._changesets.get(repo_dir)
            if cached is None or cached[0] != signature:
                cached = (signature, read_working_parent(repo_dir))
                self._changesets[repo_dir] = cached
            return cached[1]

    def _apply_collection(
        self, c: PatchCollection, key: PatchKey, changeset: str | None, current: _Input
    ) -> _FileResult:
        version_rel = c.version_file(key)
        override_rel = c.override_for(key, changeset)
        if override_rel is not None:
            result = self._apply_file(c, key, override_rel, current, override=True)
            if result is not None and _override_usable(result.states):
                return result
            if version_rel is None:
                return result or _FileResult([], None)
            log.info(
                "tool patches: %s override %s not used, falling back to %s", key_string(key), override_rel, version_rel
            )
        if version_rel is None:
            return _FileResult([], None)
        return self._apply_file(c, key, version_rel, current) or _FileResult([], None)

    def _apply_file(
        self, c: PatchCollection, key: PatchKey, rel: str, current: _Input, override: bool = False
    ) -> _FileResult | None:
        loaded = c.load(rel)
        if loaded is None:
            return None
        patch = loaded.patch
        expected_sha256 = patch.advisory.expanded_sha256 if patch.advisory else None
        if override and expected_sha256 and expected_sha256 != current.sha256():
            log.info("tool patches: %s override %s is for other content, ignored", key_string(key), rel)
            return None

        def state(kind: ChangeKind, name: PatchStateName, **fields: Any) -> PatchState:
            return PatchState(
                state=name,
                kind=kind,
                key=key_string(key),
                collection=CollectionRef(name=c.name, version=c.version),
                path=rel,
                digest=loaded.sha256,
                **{**self._unit_fields(patch, kind), **fields},
            )

        file_advisory = self._file_advisory(c, patch, key)
        states: list[PatchState] = []
        tree = current.tree
        units = plan_units(patch, self.galaxy_series)
        for unit in units:
            if unit.skipped:
                states.append(state(unit.kind, SKIPPED))
                continue
            result = evaluate_unit(tree, [op.body for op in unit.ops])
            advisory = file_advisory if patch.advisory_kind == unit.kind else None
            demotion = self._demotion(patch, unit) if result.state == APPLIED else None
            if result.state == ALREADY_APPLIED:
                states.append(state(unit.kind, ALREADY_APPLIED))
            elif result.state == APPLIED and demotion is None:
                assert result.tree is not None
                tree = result.tree
                states.append(state(unit.kind, APPLIED, advisory=advisory))
            else:
                # Demoted or mismatched: the generated advisory, then the file's own.
                if demotion is not None:
                    states.append(state(unit.kind, ADVISORY, advisory=self._generated(demotion, unit.kind, patch, key)))
                else:
                    # A python2to3 mismatch leaves the tool on Galaxy's runtime path: nothing for an admin to do.
                    generated = (
                        None if unit.kind == PYTHON2TO3 else self._generated(REVISION_MISMATCH, unit.kind, patch, key)
                    )
                    states.append(state(unit.kind, MISMATCH, advisory=generated, detail=result.detail))
                if advisory is not None:
                    states.append(state(unit.kind, ADVISORY, advisory=advisory))
        advisory_kind = patch.advisory_kind
        if file_advisory is not None and advisory_kind is not None and advisory_kind not in {u.kind for u in units}:
            states.append(state(advisory_kind, ADVISORY, advisory=file_advisory))
        return _FileResult(states, tree if tree is not current.tree else None)

    def _unit_fields(self, patch: PatchFile, kind: ChangeKind) -> dict[str, Any]:
        upstream = [u for u in patch.upstream if patch.upstream_kind(u) == kind]
        if not patch.ops_of_kind(kind):
            return {"upstream": upstream}
        if not patch.policy_governs(kind):
            return {"upstream": upstream, "reproducibility": "identical"}
        return {
            "upstream": upstream,
            "reproducibility": patch.reproducibility,
            "reproducibility_doc": patch.reproducibility_doc,
            "changes_requirements": patch.changes_requirements,
        }

    def _demotion(self, patch: PatchFile, unit: PatchUnit) -> str | None:
        """Generated code when site policy blocks an applicable unit."""
        if not patch.policy_governs(unit.kind):
            return None
        level = patch.reproducibility
        if level is not None and level_index(level) > level_index(self.policy.reproducibility):
            return REPRODUCIBILITY_ABOVE_CAP
        touches = any(op_touches_requirements(op.body) for op in unit.ops)
        if patch.changes_requirements and touches and not self.policy.requirement_changes:
            return REQUIREMENT_CHANGES_DISABLED
        return None

    def _generated(self, code: str, kind: ChangeKind, patch: PatchFile, key: PatchKey) -> AdvisoryInfo:
        entry = GENERATED_CODES[code]
        level = entry.level if kind == SECURITY or entry.level == "info" else "consider"
        fixed_in = patch.advisory.fixed_in if patch.advisory else None
        vulnerable: Vulnerable | None = None
        if kind == SECURITY:
            vulnerable = "unknown" if code == REVISION_MISMATCH else True
        message = render_message(
            entry.message, fixed_in=fixed_in, version=key[-1], reproducibility=patch.reproducibility
        )
        return AdvisoryInfo(
            code=code,
            level=level,
            action=entry.actions[0],
            fixed_in=fixed_in,
            vulnerable=vulnerable,
            message=message,
        )

    def _file_advisory(self, c: PatchCollection, patch: PatchFile, key: PatchKey) -> AdvisoryInfo | None:
        advisory = patch.advisory
        if advisory is None:
            return None
        entry = c.code(advisory.code)
        message = None
        if entry is not None:
            message = render_message(
                entry.message, fixed_in=advisory.fixed_in, version=key[-1], reproducibility=patch.reproducibility
            )
        return AdvisoryInfo(
            code=advisory.code,
            level=entry.level if entry else None,
            action=advisory.action,
            fixed_in=advisory.fixed_in,
            vulnerable=advisory.vulnerable,
            reason=advisory.reason,
            message=message,
        )


def _override_usable(states: Sequence[PatchState]) -> bool:
    """An override stands unless its security unit (or, without one, its compat unit) mismatched.

    A python2to3 mismatch never decides: the tool renders as before through Galaxy's runtime path.
    """
    mismatched = {s.kind for s in states if s.state == MISMATCH and s.kind != PYTHON2TO3}
    if SECURITY in {s.kind for s in states}:
        return SECURITY not in mismatched
    return not mismatched


def _log_state(state: PatchState) -> None:
    where = f"{state.collection.name}:{state.path}"
    if state.state == APPLIED:
        log.info("tool patches: %s %s patch applied from %s", state.key, state.kind, where)
    elif state.state == MISMATCH:
        log.warning("tool patches: %s %s patch mismatch from %s: %s", state.key, state.kind, where, state.detail)
    elif state.state == ADVISORY:
        code = state.advisory.code if state.advisory else None
        log.warning("tool patches: %s %s advisory %s from %s", state.key, state.kind, code, where)
    else:
        log.debug("tool patches: %s %s %s from %s", state.key, state.kind, state.state, where)


def load_tool_patch_database(
    paths: Sequence[str],
    reproducibility: ReproducibilityLevel = "ordinary_inputs",
    requirement_changes: bool = False,
    galaxy_series: str | None = None,
) -> ToolPatchDatabase:
    """Load collections in order; ``builtin`` names the collection shipped with this package."""
    policy = PatchPolicy.model_validate(
        {"reproducibility": reproducibility, "requirement_changes": requirement_changes}
    )
    collections = []
    for path in paths:
        directory = BUILTIN_COLLECTION_DIR if path == BUILTIN else path
        try:
            collection = PatchCollection(directory)
        except CollectionError as e:
            log.error("tool patches: skipping collection %s: %s", path, e)
            continue
        log.info("tool patches: loaded collection %s %s from %s", collection.name, collection.version, directory)
        collections.append(collection)
    return ToolPatchDatabase(collections, policy=policy, galaxy_series=galaxy_series)
