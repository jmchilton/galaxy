"""lxml helpers shared by the patch model and engine."""

import copy
import re
from functools import lru_cache

from lxml import etree

SINGLETON_TAGS = frozenset(
    {"configfiles", "command", "inputs", "outputs", "tests", "requirements", "stdio", "help", "sanitizer", "valid"}
)
REQUIREMENT_TAGS = frozenset({"requirements", "requirement", "container"})
ROOT_PATHS = (".", "")

_FRAGMENT_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_PREDICATE = re.compile(r"\[[^\]]*\]")
_REQUIREMENT_SELECTOR = re.compile(r"requirement|container")
_ROOT_IDENTITY_ATTR = re.compile(r"(^|/)\.?/?@(id|version|profile|tool_type)\b")
_ROOT_SELF = re.compile(r"^\.?(\[[^\]]*\])*$")


def parse_fragment(text: str) -> etree._Element:
    """Parse a one-element XML fragment without entity resolution or network access."""
    return etree.fromstring(text.strip().encode("utf-8"), parser=_FRAGMENT_PARSER)


def remove_keeping_tail(el: etree._Element) -> None:
    """Remove ``el`` from its parent, keeping any non-whitespace tail text in place."""
    parent = el.getparent()
    assert parent is not None
    if el.tail and el.tail.strip():
        prev = el.getprevious()
        if prev is not None:
            prev.tail = (prev.tail or "") + el.tail
        else:
            parent.text = (parent.text or "") + el.tail
    parent.remove(el)


def _normalized(el: etree._Element) -> etree._Element:
    el = copy.deepcopy(el)
    for c in list(el.iter(etree.Comment, etree.ProcessingInstruction)):
        parent = c.getparent()
        if parent is None:
            continue
        remove_keeping_tail(c)
    for e in el.iter():
        if e.text is not None and not e.text.strip() and len(e):
            e.text = None
        if e.tail is not None and not e.tail.strip():
            e.tail = None
    el.tail = None
    return el


def canon(el: etree._Element) -> bytes:
    """C14N bytes ignoring comments, whitespace-only text between children and tail."""
    return etree.tostring(_normalized(el), method="c14n")


@lru_cache(maxsize=4096)
def canon_fragment(text: str) -> bytes:
    return canon(parse_fragment(text))


def find(root: etree._Element, path: str) -> list[etree._Element]:
    if path in ROOT_PATHS:
        return [root]
    return list(root.findall(path))


def element_children(el: etree._Element) -> list[etree._Element]:
    return [c for c in el if isinstance(c.tag, str)]


def selector_is_valid(path: str) -> bool:
    if path in ROOT_PATHS:
        return True
    try:
        etree.Element("tool").findall(path)
    except (SyntaxError, KeyError, TypeError, ValueError):
        return False
    return True


def selects_root(path: str) -> bool:
    return bool(_ROOT_SELF.match(path.strip()))


def targets_root_identity(path: str) -> bool:
    return bool(_ROOT_IDENTITY_ATTR.search(path))


def selector_tag(path: str) -> str | None:
    """Tag of the last ElementPath step with predicates stripped; None for the root."""
    if selects_root(path):
        return None
    last = _PREDICATE.sub("", path).rstrip("/").split("/")[-1]
    return last or None


def selector_mentions_requirements(path: str) -> bool:
    return bool(_REQUIREMENT_SELECTOR.search(path))


def fragment_touches_requirements(text: str) -> bool:
    return any(isinstance(e.tag, str) and e.tag in REQUIREMENT_TAGS for e in parse_fragment(text).iter())
