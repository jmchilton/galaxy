"""Abstract values: the characters a user can get into a template's text, and where they come from.

An abstract value (:class:`AV`) records the probe characters a user could get into the rendered
text and their sources. A value without sources is not user-controlled. :class:`Node` is a name in
the template namespace; :class:`Group` is a section, a conditional or a repeat instance, which a
join narrows to the ``<when>`` blocks a template tested.
"""

from __future__ import annotations

import ast
import threading
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    field,
    replace,
)
from typing import (
    Callable,
    Iterator,
    List,
    Optional,
)

from .charsets import (
    Chars,
    NONE,
)
from .report import (
    Source,
    SourceRef,
)


@dataclass(frozen=True)
class AV:
    chars: Chars = NONE
    sources: frozenset[str] = frozenset()
    nodes: tuple[Node, ...] = ()
    elem: Optional[AV] = None  # element when iterated or indexed
    items: tuple[AV, ...] | None = None  # tuple or list literal
    # "shlex", "json", "pyrepr" (repr() of a list) or "pystr" (repr() of a string): the value was
    # escaped for that syntax. "sq-escaped", "dq-escaped" and "bs-escaped": the value's quotes, or with
    # "bs-escaped" the characters of `escaped`, are written escaped for the shell.
    quoted: str = ""
    # "bs-escaped": the characters the value holds only behind a backslash, and every backslash of the
    # value is one of these escapes.
    escaped: Chars = NONE
    py: str = ""  # a Python name such as "re.sub"
    # A method of another value: a str, list or dict method by name, or what calling it does.
    bound: tuple[AV, str | BoundCall] | None = None
    helper: str = ""  # a #def of the template
    # A string built in Python from literal text and values ("ln -s '%s'" % x): the pieces in order.
    parts: tuple[str | AV, ...] | None = None
    whole: bool = True  # False when a user value is only a part of this string
    # Probe characters the value can begin with, when a validator or a cleaning step narrows them.
    lead: Chars | None = None
    # Probe characters a word of the value can begin with (the value, or what follows whitespace in it).
    words: Chars | None = None
    # A value that is one of several strings built from literal text and values: each is written
    # on its own, so that the quotes in its literal text are seen.
    alts: tuple[AV, ...] = ()
    # The value of one source as the job check reads it, not changed by template code.
    verbatim: bool = False

    @property
    def tainted(self) -> bool:
        return bool(self.sources)


CLEAN = AV()
# Python writes a list as ['a', 'b']: quotes and brackets of the repr surround the user's text.
REPR_PUNCTUATION: Chars = frozenset("'\"\\ ,[](){}:")
# Marks a source that is only user-controlled under a condition; findings from it rank one level lower.
CONDITIONAL = "only when the referenced dataset is empty"


# Receives (sources, characters, escape) when the model puts characters into a user value that the
# user did not write: `escape` for the punctuation of a repr, otherwise text from the template.
_recorders = threading.local()


@contextmanager
def recording(record: Callable[[frozenset[str], Chars, bool], None]) -> Iterator[None]:
    previous = getattr(_recorders, "record", None)
    _recorders.record = record
    try:
        yield
    finally:
        _recorders.record = previous


def introduced(value: AV, chars: Chars, escape: bool = False) -> None:
    """Characters the template, not the user, can bring into this value."""
    record = getattr(_recorders, "record", None)
    if record is not None and value.tainted and chars:
        record(value.sources, chars, escape)


def tainted(chars: Chars, source: str, verbatim: bool = False) -> AV:
    """A user value; ``verbatim`` when its text in the template is the string the job check reads for it."""
    return AV(chars=chars, sources=frozenset((source,)), verbatim=verbatim)


def source(text: str, accessor: str, param: str | None = None, key: str | None = None) -> Source:
    """A source description with the input and accessor it names; the same text always gets the same reference."""
    return Source(text, SourceRef(accessor, param, key))


def concat(parts: list[str | AV]) -> AV:
    """A string made of literal text and values, in this order."""
    pieces: list[str | AV] = []
    for part in parts:
        if isinstance(part, AV):
            part = stringify(part)
            if part.parts is not None:
                pieces.extend(part.parts)
                continue
        if isinstance(part, str) and pieces and isinstance(pieces[-1], str):
            pieces[-1] += part
        elif part != "":
            pieces.append(part)
    values = [p for p in pieces if isinstance(p, AV)]
    user = [v for v in values if v.tainted]
    return AV(
        chars=frozenset().union(*(v.chars for v in values)),
        sources=frozenset().union(*(v.sources for v in values)),
        parts=tuple(pieces),
        whole=not user or (len(pieces) == 1 and user[0].whole),
    )


_QUOTES: Chars = frozenset("'\"`")
_MAX_ALTERNATIVES = 8


def _plain_string(value: AV) -> bool:
    return not value.nodes and value.elem is None and value.items is None and not value.py and value.bound is None


def _quotes_in_text(value: AV) -> bool:
    return value.parts is not None and any(isinstance(p, str) and _QUOTES.intersection(p) for p in value.parts)


def _alternatives(a: AV, b: AV) -> tuple[AV, ...] | None:
    """The strings a joined value stands for, () when one summary is enough, None when there are too many.

    Joining ``"x='" + $v + "'"`` with another string must not forget the quotes around ``$v``.
    """
    found: list[AV] = []
    for value in (a, b):
        for alternative in value.alts or (value,):
            if alternative not in found:
                found.append(alternative)
    if not all(_plain_string(v) for v in found) or not any(v.tainted and _quotes_in_text(v) for v in found):
        return ()
    # Text without a user value or a quote does not change where the other strings land.
    kept = [v for v in found if v.tainted or _quotes_in_text(v)]
    if len(kept) < len(found):
        kept.append(CLEAN)
    return tuple(kept) if len(kept) <= _MAX_ALTERNATIVES else None


def _lead(*values: AV) -> Chars | None:
    user = [v for v in values if v.tainted]
    if not any(v.lead is not None for v in user):
        return None
    return frozenset().union(*(v.lead if v.lead is not None else v.chars for v in user))


def _words(*values: AV) -> Chars | None:
    user = [v for v in values if v.tainted]
    if not any(v.words is not None for v in user):
        return None
    return frozenset().union(*(v.words if v.words is not None else v.chars for v in user))


@dataclass(frozen=True)
class ShellEscaping:
    """An escaping for the shell that a value carries (``AV.quoted``), and where it holds."""

    # The quotes the shell reads its escapes in: "" unquoted, "'" or '"'.
    quotes: frozenset[str]
    # The characters it keeps literal there.
    literal: Chars
    # What literal text or another value joined with it must not hold.
    joined: Chars
    # What the literal arguments of a str method that keeps it must not hold.
    methods: Chars
    # It still holds inside backticks, where the shell takes a backslash away before `$`, a backtick or a
    # backslash, then reads the text again.
    backticks: bool


# A str method that can add or take away a quote, a backslash or a backtick undoes a quote escape.
_QUOTING: Chars = frozenset("'\"\\`")
# '"'"' or '\'' writes a single quote inside a single-quoted word, where a backslash is a character like any
# other.
_SINGLE_QUOTE = ShellEscaping(frozenset("'"), frozenset("'"), frozenset("'"), _QUOTING, True)
# \" writes a double quote, in a value with no backslash of its own.
_DOUBLE_QUOTE = ShellEscaping(frozenset('"'), frozenset('"\\'), frozenset('"\\'), _QUOTING, False)
# A backslash and the character after it: the character, except that `\/` and `\-` are still a path and an option.
_MEANING_KEPT: Chars = frozenset("/-")


def shell_escaping(quoted: str, escaped: Chars = NONE) -> ShellEscaping | None:
    """The escaping of a value with these ``quoted`` and ``escaped``; None for one that is not for the shell."""
    if quoted == "sq-escaped":
        return _SINGLE_QUOTE
    if quoted == "dq-escaped":
        return _DOUBLE_QUOTE
    if quoted == "bs-escaped":
        covered = escaped | {"\\"}
        return ShellEscaping(frozenset(("", '"')), covered - _MEANING_KEPT, covered, covered, False)
    return None


def _text_chars(value: AV) -> Chars:
    return value.chars.union(*(frozenset(p) for p in value.parts or () if isinstance(p, str)))


def _quoted(a: AV, b: AV) -> tuple[str, Chars]:
    """How the join of two values is escaped, and its escaped characters: a value that is not user-controlled
    does not change it, unless its text holds what the escaping covers."""
    user = [v for v in (a, b) if v.tainted]
    if not user:
        return (a.quoted, a.escaped) if (a.quoted, a.escaped) == (b.quoted, b.escaped) else ("", NONE)
    if any(not v.tainted and _quotes_in_text(v) for v in (a, b)):
        # Literal text with a quote of its own ('"' + escaped): the escaping no longer lines up.
        return "", NONE
    kinds = {(v.quoted, v.escaped) for v in user if v.quoted}
    if len(kinds) != 1:
        return "", NONE
    kind, escaped = kinds.pop()
    escaping = shell_escaping(kind, escaped)
    for v in user:
        if v.quoted != kind and (escaping is None or v.chars & escaping.joined):
            return "", NONE
    if escaping is not None and any(not v.tainted and _text_chars(v) & escaping.joined for v in (a, b)):
        return "", NONE
    return kind, escaped


def _merge_narrowed(nodes: tuple[Node, ...]) -> tuple[Node, ...]:
    """The nodes with the narrowed copies of one conditional merged into one, narrowed to all their values.

    An attribute of the merged conditional is a parameter of one of their ``<when>`` blocks, as it
    is of one of the copies (:meth:`Group.attr` looks in each block).
    """
    narrowed: dict[Group, list[Group]] = {}
    for node in nodes:
        if isinstance(node, Group) and node.selector:
            narrowed.setdefault(node._origin or node, []).append(node)
    if all(len(copies) == 1 for copies in narrowed.values()):
        return nodes
    merged: dict[Node, Node] = {}
    for origin, copies in narrowed.items():
        if len(copies) > 1:
            values = frozenset().union(*(copy.case_values for copy in copies))
            whole = origin if values == origin.case_values else origin.restrict(set(values))
            for copy in copies:
                merged[copy] = whole or origin
    out: list[Node] = []
    for node in nodes:
        node = merged.get(node, node)
        if node not in out:
            out.append(node)
    return tuple(out)


def join(*values: AV | None) -> AV:
    present = [v for v in values if v is not None]
    if not present:
        return CLEAN
    out = present[0]
    for other in present[1:]:
        if other is out or other == out:
            continue
        known = set(out.nodes)
        nodes = _merge_narrowed(out.nodes + tuple(n for n in other.nodes if n not in known))
        items = None
        if out.items is not None and other.items is not None and len(out.items) == len(other.items):
            items = tuple(join(a, b) for a, b in zip(out.items, other.items))
        elem: AV | None = None
        if out.elem is not None or other.elem is not None or (items is None and (out.items or other.items)):
            elem = join(element(out, strict=True), element(other, strict=True))
        alternatives = _alternatives(out, other)
        chars = out.chars | other.chars
        bound = out.bound
        if out.bound != other.bound:
            # Callables joined with each other or anything else: a call gives what any of them can give.
            callables = [stringify(v) for v in (out, other) if v.bound is not None]
            bound = (join(*callables), joins_arguments) if callables else None
        if alternatives is None:
            # Too many strings to write one by one: assume their quotes can surround nothing.
            chars = chars | _QUOTES
            introduced(out, _QUOTES)
            introduced(other, _QUOTES)
        quoted, escaped = _quoted(out, other)
        out = AV(
            chars=chars,
            sources=out.sources | other.sources,
            nodes=nodes,
            elem=elem,
            items=items,
            quoted=quoted,
            escaped=escaped,
            py=out.py if out.py == other.py else "",
            bound=bound,
            helper=out.helper if out.helper == other.helper else "",
            whole=(out.whole or not out.tainted) and (other.whole or not other.tainted),
            lead=_lead(out, other),
            words=_words(out, other),
            alts=alternatives or (),
        )
    return out


class Node:
    """Something in the template namespace. Compared by identity."""

    path: str

    def text(self) -> AV:
        """The value written as ``$node`` or ``str($node)``."""
        return CLEAN

    def raw(self) -> AV:
        return self.text()

    def attr(self, name: str) -> AV | None:
        """``$node.name``; None when the node has no such attribute."""
        return None

    def element(self) -> AV | None:
        return None

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        """The user-controlled sources the node can give a template that mentions ``names``."""
        return iter(())


@dataclass(eq=False)
class Group(Node):
    """A section, a conditional (all of its ``<when>`` blocks) or one instance of a repeat."""

    path: str = ""
    children: dict[str, list[Node]] = field(default_factory=dict)
    # A conditional: the name of its test parameter, the <when> value of each child that is in a
    # <when> block, and every <when> value.
    selector: str = ""
    cases: dict[Node, str] = field(default_factory=dict)
    case_values: frozenset[str] = frozenset()
    # find() and restrict() results: a template looks up the same names and narrows the same
    # conditionals many times, and one object per narrowing keeps values from piling up copies.
    _found: dict[str, tuple[Node, ...]] = field(default_factory=dict, repr=False)
    _restricted: dict[frozenset[str], Group] = field(default_factory=dict, repr=False)
    # The conditional a restricted one was narrowed from.
    _origin: Group | None = field(default=None, repr=False)

    def add(self, name: str | None, node: Node) -> None:
        if name:
            self.children.setdefault(name, []).append(node)
            self._found.clear()
            self._restricted.clear()

    def restrict(self, values: set[str]) -> Group | None:
        """The conditional when its test parameter has one of these values, None for an unknown value."""
        key = frozenset(values)
        if not self.selector or not key <= self.case_values:
            return None
        # Narrowing a narrowed conditional is narrowing the original one to fewer values.
        origin = self._origin or self
        if key not in origin._restricted:
            origin._restricted[key] = origin._restrict(key)
        return origin._restricted[key]

    def _restrict(self, values: frozenset[str]) -> Group:
        # Still a conditional: an `#else if` on the same selector narrows it further.
        restricted = Group(self.path, selector=self.selector, case_values=values, _origin=self)
        for name, nodes in self.children.items():
            for node in nodes:
                if node not in self.cases:
                    restricted.add(name, node)
                elif self.cases[node] in values:
                    restricted.add(name, node)
                    restricted.cases[node] = self.cases[node]
        return restricted

    def attr(self, name: str) -> AV | None:
        # A template may name a parameter without the conditionals it is nested in: in each
        # <when> block, a parameter of the block itself, or else one nested deeper in it.
        nodes = list(self.children.get(name, []))
        if not self.selector:
            nodes = nodes or self.find(name)
        elif not any(node not in self.cases for node in nodes):
            named = {self.cases[node] for node in nodes}
            without = {value for value in self.case_values if value not in named} or (set() if nodes else None)
            for child in (node for group in self.children.values() for node in group):
                if without is None or child not in self.cases or self.cases[child] in without:
                    if isinstance(child, Group):
                        nodes.extend(n for n in child.find(name) if n not in nodes)
                    elif isinstance(child, Repeat):
                        nodes.extend(n for n in child.item.find(name) if n not in nodes)
        return AV(nodes=tuple(nodes)) if nodes else None

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        for nodes in self.children.values():
            for node in nodes:
                yield from node.sources(names)

    def find(self, name: str) -> list[Node]:
        if name not in self._found:
            found = list(self.children.get(name, []))
            for nodes in self.children.values():
                for node in nodes:
                    if isinstance(node, Group):
                        found.extend(node.find(name))
                    elif isinstance(node, Repeat):
                        found.extend(node.item.find(name))
            self._found[name] = tuple(found)
        return list(self._found[name])


@dataclass(eq=False)
class Repeat(Node):
    path: str
    item: Group

    def element(self) -> AV | None:
        return AV(nodes=(self.item,))

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        return self.item.sources(names)


def stringify(value: AV) -> AV:
    """The value as written into the output."""
    if value.nodes:
        # A value that is a parameter or a string (`getattr($p, "value", $p)`) is the text of either.
        rest = replace(value, nodes=())
        own = [stringify(rest)] if rest.tainted else []
        return join(*(node.text() for node in value.nodes), *own)
    if value.parts is not None:
        return value
    if value.elem is not None or value.items is not None:
        inner = stringify(element(value))
        if inner.tainted and not inner.chars & _REPR_ESCAPED and inner.parts is None and not inner.quoted:
            # repr() puts every string between single quotes: ['a', 'b']. Two elements show both separators.
            return concat(["['", _repr_element(inner), "', '", _repr_element(inner), "']"])
        punctuation = REPR_PUNCTUATION if inner.tainted else NONE
        if "'" not in inner.chars:
            # repr() only switches to double quotes for a string that contains a single quote.
            punctuation = punctuation - {'"'}
        introduced(inner, punctuation, escape=True)
        return AV(
            chars=value.chars | inner.chars | punctuation,
            sources=value.sources | inner.sources,
            quoted="pyrepr",
            whole=False,
        )
    if value.bound is not None:
        # What calling it can give: the body of a lambda, the value a method is bound to.
        returned = contents(value.bound[0])
        return AV(chars=returned.chars, sources=returned.sources, whole=False) if returned.tainted else CLEAN
    if value.py or value.helper:
        return CLEAN
    return AV(
        chars=value.chars,
        sources=value.sources,
        quoted=value.quoted,
        escaped=value.escaped,
        whole=value.whole,
        lead=value.lead,
        words=value.words,
        alts=value.alts,
        verbatim=value.verbatim,
    )


# Characters repr() writes differently: a string holding them is not simply put between single quotes.
_REPR_ESCAPED: Chars = frozenset("'\\\n\t\r")


def _repr_element(inner: AV) -> AV:
    return AV(chars=inner.chars, sources=inner.sources, lead=inner.lead, words=inner.words)


def contents(value: AV) -> AV:
    """What a value carries, for a function whose result is not modelled: no repr punctuation is added."""
    if (value.elem is not None or value.items is not None) and not value.nodes and value.parts is None:
        inner = contents(element(value))
        return AV(chars=value.chars | inner.chars, sources=value.sources | inner.sources, whole=False)
    return stringify(value)


def raw(value: AV) -> AV:
    if value.nodes:
        return join(*(node.raw() for node in value.nodes))
    return stringify(value)


def element(value: AV, strict: bool = False) -> AV:
    """An element of the value when iterated or indexed."""
    if value.nodes:
        # A value that is a parameter or a list (or a string) has the elements of each.
        rest = replace(value, nodes=())
        own = [element(rest, strict)] if rest.tainted or rest.elem is not None or rest.items is not None else []
        return join(*(node.element() or CLEAN for node in value.nodes), *own)
    if value.elem is not None:
        return value.elem
    if value.items is not None:
        return join(*value.items)
    if value.bound is not None:
        # `iter(f, sentinel)` gives what calls of f give.
        return stringify(value)
    if strict:
        return CLEAN
    # Iterating or slicing a string.
    return AV(chars=value.chars, sources=value.sources, whole=value.whole and value.parts is None)


# What calling a bound value does: (receiver, positional arguments, keyword arguments, the positional
# argument nodes) -> the result, or None when the call is not one it knows.
# typing.List: the alias is evaluated when the module loads, and the package supports Python 3.8.
BoundCall = Callable[["AV", List["AV"], List["AV"], List[ast.expr]], Optional["AV"]]


def returns_receiver(receiver: AV, args: list[AV], keywords: list[AV], nodes: list[ast.expr]) -> AV:
    """A method that gives what it is bound to: `$dataset.get_staging_path()`, `$x.__str__()`."""
    return receiver


def joins_arguments(receiver: AV, args: list[AV], keywords: list[AV], nodes: list[ast.expr]) -> AV:
    """A lambda: its body, which can hold any of its arguments."""
    return join(receiver, *(contents(a) for a in args + keywords))


def gets_attribute(receiver: AV, args: list[AV], keywords: list[AV], nodes: list[ast.expr]) -> AV | None:
    """`$x.__getattr__('name')` is `$x.name`."""
    name = nodes[0].value if nodes and isinstance(nodes[0], ast.Constant) else None
    return attribute(receiver, name) if isinstance(name, str) else None


# Methods of the dict a conditional or a section is, which reach its parameters by name.
GROUP_DICT_METHODS = frozenset(("get", "values", "items", "keys"))
# Every method of the dict a conditional or a section is: the read ones above, and those that change or copy it.
DICT_METHODS = frozenset(name for name in dir({}) if not name.startswith("__")) | frozenset(
    ("__setitem__", "__delitem__", "__ior__", "__or__")
)


def attribute(value: AV, name: str) -> AV:
    if name == "__str__":
        # `$x.__str__` is str($x), whatever x is.
        return AV(bound=(stringify(value), returns_receiver))
    if name == "__getattr__":
        return AV(bound=(value, gets_attribute))
    if value.nodes:
        if name in DICT_METHODS and all(isinstance(n, Group) and n.attr(name) is None for n in value.nodes):
            # The dict a conditional or a section is in the namespace: `$cond.get(name, default)`.
            return AV(bound=(value, name))
        return join(*(node.attr(name) or CLEAN for node in value.nodes))
    if value.py:
        return AV(py=f"{value.py}.{name}")
    return AV(bound=(value, name))
