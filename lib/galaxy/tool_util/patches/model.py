"""Pydantic models for tool patch files and the runtime patch state."""

from typing import (
    Annotated,
    Any,
    get_args,
    Literal,
    Self,
)

from lxml import etree
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    StrictBool,
    StrictStr,
)

from .xmlutil import (
    canon_fragment,
    fragment_touches_requirements,
    parse_fragment,
    selector_is_valid,
    selector_mentions_requirements,
    selector_tag,
    selects_root,
    targets_root_identity,
)

ChangeKind = Literal["security", "compat"]
FileKind = Literal["security", "compat", "mixed"]
ReproducibilityLevel = Literal["identical", "rejects_inputs", "unusual_inputs", "ordinary_inputs"]
AdvisoryAction = Literal["upgrade", "update_revision", "info", "enable_policy"]
FileAdvisoryAction = Literal["upgrade", "update_revision", "info"]
AdvisoryLevel = Literal["must_fix", "consider", "info"]
Vulnerable = Literal[True, "unknown"]
PatchStateName = Literal["applied", "already_applied", "mismatch", "skipped", "advisory"]

REPRODUCIBILITY_LEVELS: tuple[ReproducibilityLevel, ...] = get_args(ReproducibilityLevel)
CHANGE_KINDS: tuple[ChangeKind, ...] = get_args(ChangeKind)
SECURITY: ChangeKind = "security"
COMPAT: ChangeKind = "compat"
NEEDED_FROM_PATTERN = r"^\d{2}\.\d+$"

Occurrences = Annotated[int, Field(strict=True, gt=0)]
NeededFrom = Annotated[str, Field(strict=True, pattern=NEEDED_FROM_PATTERN)]
Sha256 = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(strict=True, min_length=1)]
GitSha = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{7,40}$")]
RepoName = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
PositiveInt = Annotated[int, Field(strict=True, gt=0)]

# Generator proposal (validator-only < sanitizer/command/configfile < everything else).
_STRUCTURAL_TAGS = frozenset({"tool", "inputs", "section", "conditional", "when", "repeat"})
_VALIDATOR_TAGS = frozenset({"validator", "param"})
_UNUSUAL_TAGS = frozenset({"sanitizer", "valid", "mapping", "add", "remove", "command", "configfile", "configfiles"})
_OPS_ONLY_FIELDS = frozenset(
    {"reproducibility", "reproducibility_doc", "reproducibility_reason", "changes_requirements", "fixes"}
)


def level_index(level: ReproducibilityLevel) -> int:
    return REPRODUCIBILITY_LEVELS.index(level)


def _check_selector(path: str, *, element_op: bool) -> None:
    if targets_root_identity(path):
        raise ValueError(f"selector {path!r} targets a root identity attribute")
    if not selector_is_valid(path):
        raise ValueError(f"invalid selector {path!r}")
    if element_op and selects_root(path):
        raise ValueError(f"selector {path!r} targets the tool root")


def _check_fragment(text: str, field: str) -> None:
    try:
        fragment = parse_fragment(text)
    except etree.XMLSyntaxError as e:
        raise ValueError(f"{field} is not an XML fragment: {e}")
    if fragment.tag == "tool":
        raise ValueError(f"{field} may not be a <tool> element")


class _FileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReplaceText(_FileModel):
    path: StrictStr
    old: NonEmptyStr
    new: NonEmptyStr
    occurrences: Occurrences

    @property
    def selector(self) -> str:
        return self.path

    @property
    def fragments(self) -> list[str]:
        return []

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_selector(self.path, element_op=False)
        if self.old == self.new:
            raise ValueError("old and new are equal")
        return self


class ReplaceElement(_FileModel):
    path: StrictStr
    old: NonEmptyStr
    new: NonEmptyStr
    occurrences: Occurrences

    @property
    def selector(self) -> str:
        return self.path

    @property
    def fragments(self) -> list[str]:
        return [self.old, self.new]

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_selector(self.path, element_op=True)
        _check_fragment(self.old, "old")
        _check_fragment(self.new, "new")
        if canon_fragment(self.old) == canon_fragment(self.new):
            raise ValueError("old and new are equal")
        return self


class AddElement(_FileModel):
    parent: StrictStr
    new: NonEmptyStr
    position: StrictStr = "last"
    occurrences: Occurrences

    @property
    def selector(self) -> str:
        return self.parent

    @property
    def fragments(self) -> list[str]:
        return [self.new]

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_selector(self.parent, element_op=False)
        _check_fragment(self.new, "new")
        if self.position not in ("first", "last"):
            side, _, child = self.position.partition(":")
            if side not in ("before", "after") or not child or not selector_is_valid(child) or selects_root(child):
                raise ValueError(f"position must be first, last, before:<path> or after:<path>, not {self.position!r}")
        return self


class RemoveElement(_FileModel):
    path: StrictStr
    old: NonEmptyStr
    occurrences: Occurrences

    @property
    def selector(self) -> str:
        return self.path

    @property
    def fragments(self) -> list[str]:
        return [self.old]

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_selector(self.path, element_op=True)
        _check_fragment(self.old, "old")
        return self


OpBody = ReplaceText | ReplaceElement | AddElement | RemoveElement


class PatchOp(_FileModel):
    replace_text: ReplaceText | None = None
    replace_element: ReplaceElement | None = None
    add_element: AddElement | None = None
    remove_element: RemoveElement | None = None
    kind: ChangeKind | None = None
    needed_from: NeededFrom | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        bodies = [b for b in (self.replace_text, self.replace_element, self.add_element, self.remove_element) if b]
        if len(bodies) != 1:
            raise ValueError("an op needs exactly one of replace_text, replace_element, add_element, remove_element")
        return self

    @property
    def body(self) -> OpBody:
        body = self.replace_text or self.replace_element or self.add_element or self.remove_element
        assert body is not None
        return body


def op_touches_requirements(body: OpBody) -> bool:
    """Static check: fragments hold requirement elements or the selector names them."""
    if selector_mentions_requirements(body.selector):
        return True
    return any(fragment_touches_requirements(f) for f in body.fragments)


def _op_tags(body: OpBody) -> set[str]:
    tags = {selector_tag(body.selector)} | {str(parse_fragment(f).tag) for f in body.fragments}
    return {t for t in tags if t is not None} - _STRUCTURAL_TAGS


def propose_level(bodies: list[OpBody]) -> ReproducibilityLevel:
    """Lowest level the op targets allow; never identical."""
    unusual = False
    for body in bodies:
        tags = _op_tags(body)
        if op_touches_requirements(body):
            return "ordinary_inputs"
        if "validator" in tags and tags <= _VALIDATOR_TAGS:
            continue
        if tags & _UNUSUAL_TAGS:
            unusual = True
        else:
            return "ordinary_inputs"
    return "unusual_inputs" if unusual else "rejects_inputs"


class UpstreamRef(_FileModel):
    repo: RepoName
    pr: PositiveInt
    merge_commit: GitSha
    kind: ChangeKind | None = None
    subset: StrictBool | None = None


class GalaxyChange(_FileModel):
    repo: RepoName
    pr: PositiveInt | None = None
    commit: GitSha | None = None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.pr is None) == (self.commit is None):
            raise ValueError("galaxy_change needs exactly one of pr or commit")
        return self


class Advisory(_FileModel):
    fixed_in: NonEmptyStr
    vulnerable: Vulnerable
    action: FileAdvisoryAction
    code: NonEmptyStr
    reason: NonEmptyStr
    kind: ChangeKind | None = None
    # advisory overrides only: ignored unless it equals the unpatched expanded sha256
    expanded_sha256: Sha256 | None = None


class PatchFile(_FileModel):
    format_version: Literal[1]
    kind: FileKind
    upstream: list[UpstreamRef] = Field(default_factory=list)
    needed_from: NeededFrom | None = None
    galaxy_change: list[GalaxyChange] | None = Field(default=None, min_length=1)
    authoring: Literal["hand"] | None = None
    # security ops the collection authored with no upstream fix
    collection_fix: Literal[True] | None = None
    reproducibility: ReproducibilityLevel | None = None
    reproducibility_doc: StrictStr | None = None
    reproducibility_reason: StrictStr | None = None
    changes_requirements: StrictBool = False
    fixes: Any = None
    ops: list[PatchOp] | None = Field(default=None, min_length=1)
    advisory: Advisory | None = None

    @field_validator("collection_fix", mode="before")
    @classmethod
    def _collection_fix_only_true(cls, value: Any) -> Any:
        if value is not True:
            raise ValueError("collection_fix is written only when true")
        return value

    def _default_kind(self) -> ChangeKind | None:
        return None if self.kind == "mixed" else self.kind

    def op_kind(self, op: PatchOp) -> ChangeKind:
        kind = op.kind or self._default_kind()
        assert kind is not None
        return kind

    def op_needed_from(self, op: PatchOp) -> str | None:
        if self.op_kind(op) != COMPAT:
            return None
        return op.needed_from or self.needed_from

    def upstream_kind(self, upstream: UpstreamRef) -> ChangeKind | None:
        return upstream.kind or self._default_kind()

    @property
    def advisory_kind(self) -> ChangeKind | None:
        if self.advisory is None:
            return None
        return self.advisory.kind or self._default_kind()

    def ops_of_kind(self, kind: ChangeKind) -> list[PatchOp]:
        return [op for op in self.ops or [] if self.op_kind(op) == kind]

    def policy_governs(self, kind: ChangeKind) -> bool:
        """True when reproducibility and changes_requirements describe ops of this kind."""
        return self.kind != "mixed" or kind == SECURITY

    def policy_ops(self) -> list[PatchOp]:
        """Ops that reproducibility and changes_requirements describe."""
        return [op for op in self.ops or [] if self.policy_governs(self.op_kind(op))]

    @model_validator(mode="after")
    def _check_rules(self) -> Self:
        ops = self.ops or []
        if not ops and self.advisory is None:
            raise ValueError("a patch file needs ops, an advisory or both")
        if self.kind == "mixed":
            if any(op.kind is None for op in ops):
                raise ValueError("every op in a mixed file needs kind")
            if any(u.kind is None for u in self.upstream):
                raise ValueError("every upstream entry in a mixed file needs kind")
            if self.advisory is not None and self.advisory.kind is None:
                raise ValueError("the advisory in a mixed file needs kind")
            if {self.op_kind(op) for op in ops} != set(CHANGE_KINDS):
                raise ValueError("a mixed file needs both security and compat ops")
        elif any(op.kind not in (None, self.kind) for op in ops):
            raise ValueError(f"op kind must equal the file kind {self.kind!r}")
        for i, op in enumerate(ops):
            if self.op_kind(op) == SECURITY and op.needed_from is not None:
                raise ValueError(f"op {i}: security ops never have needed_from")
            if self.op_kind(op) == COMPAT and self.op_needed_from(op) is None:
                raise ValueError(f"op {i}: compat ops need needed_from (on the op or the file)")
        has_compat = bool(self.ops_of_kind(COMPAT))
        if self.needed_from is not None and not has_compat:
            raise ValueError("needed_from is only for files with compat ops")
        if has_compat != (self.galaxy_change is not None):
            raise ValueError("galaxy_change is required with compat ops and forbidden otherwise")
        if ops:
            self._check_ops_fields()
        else:
            carried = sorted(_OPS_ONLY_FIELDS & self.model_fields_set)
            if carried:
                raise ValueError(f"an advisory-only file can't carry {carried}")
        has_security_ops = bool(self.ops_of_kind(SECURITY))
        if self.collection_fix:
            if self.authoring != "hand":
                raise ValueError("collection_fix needs authoring: hand")
            if not has_security_ops:
                raise ValueError("collection_fix needs security ops")
        needs_security_upstream = (has_security_ops and not self.collection_fix) or self.advisory_kind == SECURITY
        if needs_security_upstream and not any(self.upstream_kind(u) == SECURITY for u in self.upstream):
            raise ValueError("security ops or advisories need a security upstream entry")
        return self

    def _check_ops_fields(self) -> None:
        if self.reproducibility is None:
            raise ValueError("reproducibility is required with ops")
        if not (self.reproducibility_doc or "").strip():
            raise ValueError("reproducibility_doc is required with ops")
        if self.reproducibility_reason is not None and not self.reproducibility_reason.strip():
            raise ValueError("reproducibility_reason must be non-empty when present")
        if self.kind == COMPAT and self.reproducibility != "identical":
            raise ValueError("compat ops must be reproducibility: identical")
        if self.kind == "mixed" and any(op_touches_requirements(op.body) for op in self.ops_of_kind(COMPAT)):
            raise ValueError("compat ops in a mixed file can't touch requirements")
        bodies = [op.body for op in self.policy_ops()]
        touches = any(op_touches_requirements(b) for b in bodies)
        if touches != self.changes_requirements:
            raise ValueError(f"changes_requirements must be {touches} for these ops")
        proposed = propose_level(bodies)
        if level_index(self.reproducibility) < level_index(proposed) and not self.reproducibility_reason:
            raise ValueError(f"reproducibility below the proposed {proposed!r} needs reproducibility_reason")


class CodeEntry(_FileModel):
    level: AdvisoryLevel
    message: StrictStr
    url: StrictStr | None = None
    actions: list[AdvisoryAction]


class CodesFile(_FileModel):
    format_version: Literal[1]
    codes: dict[str, CodeEntry]


# --- runtime state (serialized onto index entries and tools) ---


class CollectionRef(BaseModel):
    name: str
    version: str


class AdvisoryInfo(BaseModel):
    code: str
    level: AdvisoryLevel | None = None
    action: AdvisoryAction
    fixed_in: str | None = None
    vulnerable: Vulnerable | None = None
    reason: str | None = None
    message: str | None = None


class PatchState(BaseModel):
    state: PatchStateName
    kind: ChangeKind
    key: str
    collection: CollectionRef
    path: str
    digest: str
    upstream: list[UpstreamRef] = Field(default_factory=list)
    reproducibility: ReproducibilityLevel | None = None
    reproducibility_doc: str | None = None
    changes_requirements: bool = False
    advisory: AdvisoryInfo | None = None
    verified: bool | None = None
    detail: str | None = None


class ToolPatchInfo(BaseModel):
    digest: str | None = None
    states: list[PatchState] = Field(default_factory=list)


def patches_as_dicts(patch: ToolPatchInfo | None) -> list[dict[str, Any]] | None:
    """API form of a tool's patch states, or None for an unpatched tool."""
    if patch is None or not patch.states:
        return None
    return [state.model_dump(mode="json") for state in patch.states]


class PatchPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    reproducibility: ReproducibilityLevel = "ordinary_inputs"
    requirement_changes: bool = False


class CollectionSummary(BaseModel):
    name: str
    version: str
    digest: str


class ToolPatchCollectionsSummary(BaseModel):
    collections: list[CollectionSummary] = Field(default_factory=list)
    policy: PatchPolicy = Field(default_factory=PatchPolicy)
    galaxy_series: str | None = None
