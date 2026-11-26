"""Classify and apply patch ops on a macro-expanded tool tree."""

import copy
import logging
from collections.abc import Sequence
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
)

from lxml import etree

from galaxy.tool_util.parameters.factory import input_models_for_tool_source
from galaxy.tool_util.parser.xml import XmlToolSource
from galaxy.util import ElementTree
from .model import (
    AddElement,
    CHANGE_KINDS,
    ChangeKind,
    op_selector,
    OpBody,
    PatchFile,
    PatchOp,
    RemoveElement,
    ReplaceElement,
    ReplaceText,
)
from .xmlutil import (
    canon,
    canon_fragment,
    element_children,
    find,
    parse_fragment,
    SINGLETON_TAGS,
)

log = logging.getLogger(__name__)

PRE, POST, NEITHER = "pre", "post", "neither"
APPLIED, ALREADY_APPLIED, MISMATCH, SKIPPED = "applied", "already_applied", "mismatch", "skipped"
PARAMETER_MODEL_CHANGED = "parameter model changed"


def _spans(text: str, needle: str) -> list[tuple[int, int]]:
    out = []
    i = text.find(needle)
    while i >= 0:
        out.append((i, i + len(needle)))
        i = text.find(needle, i + len(needle))
    return out


def _outside(text: str, old: str, new: str) -> int:
    """Occurrences of old not contained in an occurrence of new."""
    news = _spans(text, new)
    return sum(1 for a, b in _spans(text, old) if not any(x <= a and b <= y for x, y in news))


def _ancestors(el: etree._Element) -> list[etree._Element]:
    out = []
    parent = el.getparent()
    while parent is not None:
        out.append(parent)
        parent = parent.getparent()
    return out


def _position_index(parent: etree._Element, position: str) -> int | None:
    """Insertion index for position, or None unless the anchor is exactly one direct child."""
    children = list(parent)
    if position == "first":
        return 0
    if position == "last":
        return len(children)
    side, _, child_path = position.partition(":")
    hits = [c for c in parent.findall(child_path) if c.getparent() is parent]
    if len(hits) != 1:
        return None
    i = children.index(hits[0])
    return i if side == "before" else i + 1


def classify(root: etree._Element, body: OpBody) -> str:
    """PRE, POST or NEITHER for one op; the post-image is checked first."""
    n = body.occurrences
    if isinstance(body, ReplaceText):
        texts = [e.text or "" for e in find(root, body.path)]
        if not texts:
            return NEITHER
        if sum(t.count(body.new) for t in texts) == n and not any(_outside(t, body.old, body.new) for t in texts):
            return POST
        if sum(t.count(body.old) for t in texts) == n:
            return PRE
        return NEITHER
    if isinstance(body, ReplaceElement):
        candidates = find(root, body.path)
        if any(c is root for c in candidates):
            return NEITHER
        c_old, c_new = canon_fragment(body.old), canon_fragment(body.new)
        keyed = [(c, canon(c)) for c in candidates]
        news = [c for c, k in keyed if k == c_new]
        olds = [c for c, k in keyed if k == c_old]
        olds_outside = [c for c in olds if not any(a in news for a in _ancestors(c))]
        if len(news) == n and not olds_outside:
            return POST
        if len(olds) == n:
            return PRE
        return NEITHER
    if isinstance(body, AddElement):
        parents = find(root, body.parent)
        if len(parents) != n:
            return NEITHER
        c_new = canon_fragment(body.new)
        has = [any(canon(ch) == c_new for ch in element_children(p)) for p in parents]
        if all(has):
            return POST
        if any(has):
            return NEITHER
        tag = parse_fragment(body.new).tag
        for p in parents:
            if tag in SINGLETON_TAGS and any(ch.tag == tag for ch in element_children(p)):
                return NEITHER
            if _position_index(p, body.position) is None:
                return NEITHER
        return PRE
    candidates = find(root, body.path)
    if any(c is root for c in candidates):
        return NEITHER
    c_old = canon_fragment(body.old)
    olds = [c for c in candidates if canon(c) == c_old]
    if not olds:
        return POST
    return PRE if len(olds) == n else NEITHER


def apply_op(root: etree._Element, body: OpBody) -> None:
    """Apply one op in place; callers classify it as PRE first."""
    if isinstance(body, ReplaceText):
        for e in find(root, body.path):
            if e.text:
                e.text = e.text.replace(body.old, body.new)
    elif isinstance(body, ReplaceElement):
        c_old = canon_fragment(body.old)
        for e in [c for c in find(root, body.path) if canon(c) == c_old]:
            new = parse_fragment(body.new)
            new.tail = e.tail
            parent = e.getparent()
            assert parent is not None
            parent.replace(e, new)
    elif isinstance(body, AddElement):
        for p in find(root, body.parent):
            new = parse_fragment(body.new)
            i = _position_index(p, body.position)
            assert i is not None
            children = list(p)
            ref = children[i - 1] if i > 0 else None
            new.tail = (ref.tail if ref is not None else p.text) if children else None
            p.insert(i, new)
    else:
        c_old = canon_fragment(body.old)
        for e in [c for c in find(root, body.path) if canon(c) == c_old]:
            parent = e.getparent()
            assert parent is not None
            if e.tail and e.tail.strip():
                prev = e.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + e.tail
                else:
                    parent.text = (parent.text or "") + e.tail
            parent.remove(e)


def selector_counts(root: etree._Element, bodies: Sequence[OpBody]) -> list[int]:
    return [len(find(root, op_selector(body))) for body in bodies]


def _parameter_model(tree: ElementTree) -> Any:
    """Parameter model with validators and sanitizers stripped."""
    root = copy.deepcopy(tree.getroot())
    for el in list(root.iter("validator", "sanitizer")):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)
    for el in root.iter("options"):
        if "sanitize" in el.attrib:
            del el.attrib["sanitize"]
    source = XmlToolSource(cast(ElementTree, etree.ElementTree(root)))
    return input_models_for_tool_source(source).model_dump(mode="json")


def _same_model(before: Any, after: Any) -> bool:
    """Equal, except options unknown before (None, e.g. from_file) may be filled in after."""
    if isinstance(before, dict) and isinstance(after, dict):
        if before.keys() != after.keys():
            return False
        return all((key == "options" and before[key] is None) or _same_model(before[key], after[key]) for key in before)
    if isinstance(before, list) and isinstance(after, list):
        return len(before) == len(after) and all(_same_model(b, a) for b, a in zip(before, after))
    return bool(before == after)


def parameter_model_changed(before: ElementTree, after: ElementTree) -> bool:
    try:
        pre = _parameter_model(before)
    except Exception as e:
        log.debug("parameter model unavailable for the unpatched tool, not checking it: %s", e)
        return False
    try:
        post = _parameter_model(after)
    except Exception:
        return True
    return not _same_model(pre, post)


@dataclass
class UnitResult:
    state: str
    tree: ElementTree | None = None
    detail: str | None = None


def evaluate_unit(tree: ElementTree, bodies: Sequence[OpBody], check_parameter_model: bool = True) -> UnitResult:
    """Evaluate one atomic unit of ops; the input tree is never mutated."""
    root = tree.getroot()
    classes = [classify(root, body) for body in bodies]
    if all(c == POST for c in classes):
        return UnitResult(ALREADY_APPLIED)
    if any(c != PRE for c in classes):
        return UnitResult(MISMATCH, detail=", ".join(f"op {i}: {c}" for i, c in enumerate(classes)))
    work = copy.deepcopy(tree)
    work_root = work.getroot()
    for i, body in enumerate(bodies):
        if classify(work_root, body) != PRE:
            return UnitResult(MISMATCH, detail=f"op {i} no longer applies after the earlier ops")
        apply_op(work_root, body)
    for i, body in enumerate(bodies):
        if classify(work_root, body) != POST:
            return UnitResult(MISMATCH, detail=f"op {i} is not idempotent")
    before = selector_counts(root, bodies)
    after = selector_counts(work_root, bodies)
    for i, body in enumerate(bodies):
        expected = before[i] - body.occurrences if isinstance(body, RemoveElement) else before[i]
        if after[i] != expected:
            return UnitResult(
                MISMATCH, detail=f"op {i} selector matched {before[i]} elements before and {after[i]} after"
            )
    if check_parameter_model and parameter_model_changed(tree, work):
        return UnitResult(MISMATCH, detail=PARAMETER_MODEL_CHANGED)
    return UnitResult(APPLIED, tree=work)


def _series(value: str) -> tuple[int, int]:
    major, minor = value.split(".")
    return int(major), int(minor)


def series_satisfied(needed_from: str | None, galaxy_series: str | None) -> bool:
    """None for galaxy_series evaluates every op."""
    return galaxy_series is None or needed_from is None or _series(galaxy_series) >= _series(needed_from)


@dataclass
class PatchUnit:
    kind: ChangeKind
    ops: list[PatchOp] = field(default_factory=list)
    skipped: bool = False


def plan_units(patch_file: PatchFile, galaxy_series: str | None) -> list[PatchUnit]:
    """Security ops first, then compat ops; ops gated out by needed_from are dropped."""
    units = []
    for kind in CHANGE_KINDS:
        ops = patch_file.ops_of_kind(kind)
        if not ops:
            continue
        active = [op for op in ops if series_satisfied(patch_file.op_needed_from(op), galaxy_series)]
        units.append(PatchUnit(kind=kind, ops=active, skipped=not active))
    return units
