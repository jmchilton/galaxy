"""What a template can read, and how much of it a user controls.

Every name a ``<command>`` template can reference is modelled as a node (a parameter, a
dataset, a collection, a group of parameters). The semantics mirror the wrappers Galaxy
puts into the template namespace (``galaxy.tools.wrappers``): the same parameter gives a
sanitized string when written as ``$param`` and the raw submitted value through
``$param.value`` or a string method.

An abstract value (:class:`AV`) records the probe characters a user could get into the
rendered text and where they come from. A value without sources is not user-controlled.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import (
    dataclass,
    field,
    replace,
)
from typing import (
    Any,
    Callable,
    Iterator,
    Optional,
)

from galaxy.tool_util.parser.interface import (
    InputSource,
    ToolSource,
)
from galaxy.tool_util.parser.sanitize import ToolParameterSanitizer
from galaxy.util.xml_macros import template_macro_params
from .charsets import (
    Chars,
    DEFAULT_SANITIZED,
    NONE,
    PROBE,
    sanitized,
)
from .report import (
    DATASET_ATTRIBUTE,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW,
    Source,
    SourceRef,
    SPECIAL,
    TEXT,
)
from .validators import text_constraint


@dataclass(frozen=True)
class AV:
    chars: Chars = NONE
    sources: frozenset[str] = frozenset()
    nodes: tuple[Node, ...] = ()
    elem: Optional[AV] = None  # element when iterated or indexed
    items: tuple[AV, ...] | None = None  # tuple or list literal
    quoted: str = ""  # "shlex", "json" or "pyrepr": the value was escaped for that syntax
    py: str = ""  # a Python name such as "re.sub"
    bound: tuple[AV, str] | None = None  # a method of another value
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


def tainted(chars: Chars, source: str) -> AV:
    return AV(chars=chars, sources=frozenset((source,)))


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


# The other values a value escaped for this syntax may be joined with: they cannot hold what the escaping covers.
_ESCAPED: dict[str, Chars] = {"sq-escaped": frozenset("'"), "dq-escaped": frozenset('"\\')}


def _quoted(a: AV, b: AV) -> str:
    """How the join of two values is escaped: a value that is not user-controlled does not change it."""
    user = [v for v in (a, b) if v.tainted]
    if not user:
        return a.quoted if a.quoted == b.quoted else ""
    if any(not v.tainted and _quotes_in_text(v) for v in (a, b)):
        # Literal text with a quote of its own ('"' + escaped): the escaping no longer lines up.
        return ""
    kinds = {v.quoted for v in user if v.quoted}
    if len(kinds) != 1:
        return ""
    kind = kinds.pop()
    covered = _ESCAPED.get(kind)
    for v in user:
        if v.quoted != kind and (covered is None or v.chars & covered):
            return ""
    return kind


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
        if alternatives is None:
            # Too many strings to write one by one: assume their quotes can surround nothing.
            chars = chars | _QUOTES
            introduced(out, _QUOTES)
            introduced(other, _QUOTES)
        out = AV(
            chars=chars,
            sources=out.sources | other.sources,
            nodes=nodes,
            elem=elem,
            items=items,
            quoted=_quoted(out, other),
            py=out.py if out.py == other.py else "",
            bound=out.bound if out.bound == other.bound else None,
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


@dataclass(eq=False)
class Value(Node):
    """A parameter whose value is text: text, select, column, tag, number, boolean..."""

    path: str
    type: str
    as_text: AV = CLEAN
    as_raw: AV = CLEAN
    as_element: AV | None = None
    text_like: bool = False  # unknown attributes are string methods of the raw value

    def text(self) -> AV:
        return self.as_text

    def raw(self) -> AV:
        return self.as_raw

    def attr(self, name: str) -> AV | None:
        if name == "value":
            return self.as_raw
        if name == "fields":
            return AV(nodes=(Opaque(f"{self.path}.fields", self.as_raw),))
        if name == "value_label":
            return self.as_raw
        if self.text_like:
            return AV(bound=(self.as_raw, name))
        # Any other attribute of a select wrapper is an attribute of the parameter definition.
        return CLEAN

    def element(self) -> AV | None:
        return self.as_element if self.as_element is not None else self.as_text


@dataclass(eq=False)
class Opaque(Node):
    """An object whose every attribute, item and call result is the same kind of value."""

    path: str
    value: AV = CLEAN

    def text(self) -> AV:
        return self.value

    def attr(self, name: str) -> AV | None:
        return AV(chars=self.value.chars, sources=self.value.sources, nodes=(self,))

    def element(self) -> AV | None:
        return AV(chars=self.value.chars, sources=self.value.sources, nodes=(self,))


# Attributes of a dataset wrapper that Galaxy computes itself.
_DATA_CLEAN = frozenset(
    (
        "ext extension file_ext id hid is_collection is_of_type is_deferred has_single_item extra_files_path"
        " files_path file_name path safe_element_identifier uuid state datatype all_metadata_files size"
        " get_size has_data serialize is_input_supplied"
    ).split()
)
_METADATA_CLEAN = frozenset(
    "columns data_lines comment_lines sequences column_types delimiter blocks bases number_of_models".split()
)


@dataclass(eq=False)
class Data(Node):
    path: str
    multiple: bool = False
    sanitize: bool = True
    output: bool = False

    def _safe_string(self, what: str, accessor: str = DATASET_ATTRIBUTE, key: str | None = None) -> AV:
        # Attributes of the dataset go through SafeStringWrapper: Galaxy's default sanitizer.
        return tainted(
            DEFAULT_SANITIZED if self.sanitize else PROBE,
            source(f"{what} of dataset '{self.path}'", accessor, self.path, key),
        )

    def attr(self, name: str) -> AV | None:
        if self.output:
            return CLEAN
        if name in ("element_identifier", "name_and_ext"):
            return tainted(
                PROBE,
                source(f"element identifier of dataset '{self.path}' (not sanitized)", ELEMENT_IDENTIFIER, self.path),
            )
        if name == "groups":
            return AV(
                elem=tainted(
                    PROBE, source(f"group tags of dataset '{self.path}' (not sanitized)", GROUP_TAGS, self.path)
                )
            )
        if name == "get_staging_path":
            staged = source(f"element identifier of dataset '{self.path}'", ELEMENT_IDENTIFIER, self.path)
            return AV(bound=(tainted(PROBE - {"/"}, staged), "__value__"))
        if name == "metadata":
            return AV(nodes=(Metadata(self.path, self),))
        if name == "unsanitized":
            raw_model = source(f"raw model of dataset '{self.path}'", OPAQUE, self.path)
            return AV(nodes=(RawDataset(f"{self.path}.unsanitized", tainted(PROBE, raw_model)),))
        if name == "dataset":
            return AV(nodes=(DatasetObject(self.path, self),))
        if name == "single_item":
            return AV(nodes=(self,))
        if name in _DATA_CLEAN:
            return CLEAN
        return self._safe_string("name" if name == "name" else f"attribute '{name}'", key=name)

    def element(self) -> AV | None:
        return AV(nodes=(self,))


# Attributes of a dataset model that Galaxy sets itself: its type, its id, its paths and state.
_RAW_DATASET_CLEAN = frozenset(
    "ext extension id hid extra_files_path get_file_name file_name get_size has_data state".split()
)


@dataclass(eq=False)
class RawDataset(Opaque):
    """``$input.unsanitized``: the dataset model itself, whose strings are not sanitized."""

    def attr(self, name: str) -> AV | None:
        if name in _RAW_DATASET_CLEAN:
            return CLEAN
        if name == "metadata":
            return AV(nodes=(RawMetadata(f"{self.path}.metadata", self.value),))
        return super().attr(name)


@dataclass(eq=False)
class RawMetadata(Opaque):
    """The metadata of a dataset model: Galaxy computes some of it from the file."""

    def attr(self, name: str) -> AV | None:
        if name in _METADATA_CLEAN or name.endswith(("_index", "Col")):
            return CLEAN
        return super().attr(name)


@dataclass(eq=False)
class DatasetObject(Node):
    """``$input.dataset``: the dataset behind SafeStringWrapper, strings are sanitized, paths are Galaxy's."""

    path: str
    data: Data

    def attr(self, name: str) -> AV | None:
        if name in _DATA_CLEAN or name in ("get_file_name", "dataset", "metadata"):
            return CLEAN if name != "dataset" else AV(nodes=(self,))
        return self.data._safe_string(f"attribute '{name}'", key=name)


@dataclass(eq=False)
class Metadata(Node):
    path: str
    data: Data

    def attr(self, name: str) -> AV | None:
        if name in _METADATA_CLEAN or name.endswith(("_index", "Col")) or name in ("get", "items", "element_is_set"):
            return CLEAN
        return self.data._safe_string(f"metadata '{name}'", METADATA, name)


@dataclass(eq=False)
class Collection(Node):
    path: str
    nested: bool | None = None  # None: the collection type is not declared
    sanitize: bool = True
    output: bool = False

    def _identifier(self) -> AV:
        # `$c.name` of the collection input is its name, of a nested collection its element identifier.
        return tainted(
            PROBE,
            source(f"element identifier of collection '{self.path}' (not sanitized)", ELEMENT_IDENTIFIER, self.path),
        )

    def element(self) -> AV | None:
        if self.output:
            return CLEAN
        nodes: list[Node] = []
        if self.nested is not True:
            nodes.append(Data(self.path, sanitize=self.sanitize))
        if self.nested is not False:
            nodes.append(Collection(self.path, nested=None, sanitize=self.sanitize))
        return AV(nodes=tuple(nodes))

    def attr(self, name: str) -> AV | None:
        if self.output:
            return CLEAN
        if name in ("name", "element_identifier"):
            return self._identifier()
        if name == "keys":
            return AV(bound=(AV(elem=self._identifier()), "__value__"))
        if name == "items":
            pair = AV(items=(self._identifier(), self.element() or CLEAN))
            return AV(bound=(AV(elem=pair), "__value__"))
        if name == "values":
            return AV(bound=(AV(elem=self.element()), "__value__"))
        if name == "get_datasets_for_group":
            # The datasets of the collection, at any depth, whose tags name the group.
            return AV(bound=(AV(elem=AV(nodes=(Data(self.path, sanitize=self.sanitize),))), "__value__"))
        if name in ("element_identifiers_extensions_paths_and_metadata_files", "sample_sheet_row"):
            return AV(nodes=(Opaque(f"{self.path}.{name}", self._identifier()),))
        if name == "get_all_staging_paths":
            staged = tainted(
                PROBE - {"/"}, source(f"element identifier of collection '{self.path}'", ELEMENT_IDENTIFIER, self.path)
            )
            return AV(bound=(AV(elem=staged), "__value__"))
        if (
            name
            in (
                "safe_element_identifier is_collection all_paths all_metadata_files has_single_item"
                " is_input_supplied collection serialize paths_as_file"
            ).split()
        ):
            return CLEAN
        # Anything else is an element looked up by its identifier ($pair.forward).
        return self.element()


@dataclass(eq=False)
class Special(Node):
    """A value Galaxy adds to the namespace itself."""

    path: str
    value: AV = CLEAN
    opaque: AV | None = None

    def text(self) -> AV:
        return self.value

    def attr(self, name: str) -> AV | None:
        if self.opaque is not None:
            return AV(nodes=(Opaque(f"{self.path}.{name}", self.opaque),))
        return CLEAN


def file_content() -> AV:
    """What ``open(path)`` gives a template: the content of a file, which is a dataset unless shown otherwise."""
    content = tainted(PROBE, source("content of a file the template reads with open() (not sanitized)", OPAQUE))
    return AV(nodes=(Opaque("open()", content),))


def stringify(value: AV) -> AV:
    """The value as written into the output."""
    if value.nodes:
        return join(*(node.text() for node in value.nodes))
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
    if value.bound is not None or value.py or value.helper:
        return CLEAN
    return AV(
        chars=value.chars,
        sources=value.sources,
        quoted=value.quoted,
        whole=value.whole,
        lead=value.lead,
        words=value.words,
        alts=value.alts,
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
    if strict:
        return CLEAN
    # Iterating or slicing a string.
    return AV(chars=value.chars, sources=value.sources, whole=value.whole and value.parts is None)


def attribute(value: AV, name: str) -> AV:
    if name == "__str__":
        # `$x.__str__` is str($x), whatever x is.
        return AV(bound=(stringify(value), "__value__"))
    if value.nodes:
        return join(*(node.attr(name) or CLEAN for node in value.nodes))
    if value.py:
        return AV(py=f"{value.py}.{name}")
    return AV(bound=(value, name))


_SAFE_SPECIALS = (
    "__tool_directory__ __root_dir__ __new_file_path__ __tool_data_path__ __datatypes_config__ __galaxy_url__"
    " __history_id__ __local_working_directory__ __get_data_table_entry__ __admin_users__ GALAXY_DATA_INDEX_DIR"
    " GALAXY_ROOT_DIR GALAXY_DATATYPES_CONF_FILE chromInfo __user_id__ userId user_id __job_resource"
).split()
SAFE_SPECIALS = frozenset(_SAFE_SPECIALS)
_USER_SPECIALS = "__user_email__ userEmail __user_name__ dbkey".split()

# Select-like parameter types whose values come from the user's data.
_USER_SELECT_TYPES = frozenset(("data_column", "group_tag", "genomebuild"))


@dataclass
class Model:
    root: Group
    sanitize: bool = True
    configfiles: dict[str, str] = field(default_factory=dict)
    specials: dict[str, Special] = field(default_factory=dict)
    # Template macros: Cheetah text the template can read in with `#include source=$name#`.
    templates: dict[str, str] = field(default_factory=dict)
    _job_parameters: dict[str, Opaque] = field(default_factory=dict, repr=False)

    def job_parameter(self, name: str) -> AV:
        """A name that is not a tool input: only a job parameter of that name can give it a value.

        Galaxy puts every parameter of the job into the namespace, sanitized like a text parameter.
        A regular job only has the parameters of the tool's inputs, and the template fails where it
        reads any other name.
        """
        if name not in self._job_parameters:
            chars = DEFAULT_SANITIZED if self.sanitize else PROBE
            value = tainted(chars, source(f"job parameter ${name}, which is not a tool input", SPECIAL, key=name))
            self._job_parameters[name] = Opaque(f"${name}", value)
        return AV(nodes=(self._job_parameters[name],))

    def lookup(self, name: str) -> AV | None:
        nodes = self.root.children.get(name)
        if nodes:
            return AV(nodes=tuple(nodes))
        if name in self.specials:
            return AV(nodes=(self.specials[name],))
        # Old tools address nested parameters by their bare name.
        found = self.root.find(name)
        if found:
            return AV(nodes=tuple(found))
        # Galaxy also adds each dataset of a multiple data input by its position: $input1, $input2.
        end = len(name)
        while end > 1 and name[end - 1].isdigit():
            end -= 1
            datasets = [node for node in self.root.children.get(name[:end], ()) if isinstance(node, Data)]
            if datasets:
                return AV(nodes=tuple(datasets))
        return None


def _user_select(input_source: InputSource) -> str | None:
    """Why the options of a select come from user data, None when the tool or the admin defines them."""
    ptype = input_source.get("type")
    if ptype in _USER_SELECT_TYPES:
        return str(ptype)
    if input_source.get("dynamic_options"):
        return "select with options from code"
    dynamic = input_source.parse_dynamic_options()
    if dynamic is None:
        return None
    elem = dynamic.elem()
    if elem.get("from_dataset") or elem.get("from_url"):
        return "select with options from a dataset"
    if elem.get("from_file") or elem.get("from_data_table") or elem.get("from_parameter"):
        return None
    if any(f.get("type") == "data_meta" for f in elem.findall("filter")):
        return "select with options from dataset metadata"
    return None


def _escapes_single_quote(sanitizer: ToolParameterSanitizer | None) -> bool:
    """The sanitizer rewrites ' to the sequence that writes a quote inside a single-quoted shell word."""
    return sanitizer is not None and sanitizer.sanitize_param("'") in ("'\"'\"'", "'\\''")


def _value(input_source: InputSource, path: str, tool_sanitize: bool) -> Node:
    ptype = input_source.get("type") or "text"
    if ptype in ("data", "hidden_data"):
        return Data(path, multiple=input_source.get_bool("multiple", False), sanitize=tool_sanitize)
    if ptype == "data_collection":
        types = [t.strip() for t in (input_source.get("collection_type") or "").split(",") if t.strip()]
        nested = any(":" in t for t in types) if types else None
        return Collection(path, nested=nested, sanitize=tool_sanitize)
    if ptype in ("integer", "float", "boolean", "baseurl", "rules"):
        return Value(path, ptype)

    sanitizer_elem = input_source.parse_sanitizer_elem()
    sanitizer = ToolParameterSanitizer.from_element(sanitizer_elem) if sanitizer_elem is not None else None

    def rendered(chars: Chars) -> Chars:
        return sanitized(chars, sanitizer) if tool_sanitize else chars

    if ptype in ("select", "drill_down") or ptype in _USER_SELECT_TYPES:
        reason = _user_select(input_source)
        if reason is None:
            return Value(path, ptype)
        label = f"{reason} param '{path}'" if reason in _USER_SELECT_TYPES else f"'{path}' ({reason})"
        if ptype == "data_column":
            # Galaxy checks a column against the dataset's columns, except for an empty dataset.
            label += f", {CONDITIONAL}"
        as_raw = tainted(PROBE, source(f"raw value of {label} (not sanitized)", RAW, path))
        as_text = tainted(rendered(PROBE), source(label, TEXT, path))
        return Value(path, ptype, as_text=as_text, as_raw=as_raw, as_element=as_raw)

    constraint = text_constraint(input_source)
    universe = constraint.chars
    # Only a start that is narrower than the rest of the value is worth carrying.
    lead = constraint.lead if "-" in universe and "-" not in constraint.lead else None
    word_first = constraint.word_first()
    words = word_first if "-" in universe and "-" not in word_first else None
    if ptype in ("color", "directory_uri", "file", "ftpfile"):
        # These types return the submitted value as it is: no sanitizer runs when they are rendered.
        value = AV(
            chars=universe,
            # The rendered text is the submitted value.
            sources=frozenset((source(f"{ptype} param '{path}' (not sanitized)", RAW, path),)),
            lead=lead,
            words=words,
        )
        return Value(path, ptype, as_text=value, as_raw=value, text_like=True)
    # text, hidden and anything unknown.
    return Value(
        path,
        ptype,
        as_text=AV(
            chars=rendered(universe),
            sources=frozenset((source(f"{ptype} param '{path}'", TEXT, path),)),
            quoted="sq-escaped" if tool_sanitize and _escapes_single_quote(sanitizer) else "",
            lead=rendered(lead) if lead is not None else None,
            words=rendered(words) if words is not None else None,
        ),
        as_raw=AV(
            chars=universe,
            sources=frozenset((source(f"raw value of {ptype} param '{path}' (sanitizer bypassed)", RAW, path),)),
            lead=lead,
            words=words,
        ),
        text_like=True,
    )


def _add_inputs(group: Group, input_sources: list[InputSource], prefix: str, tool_sanitize: bool) -> None:
    for input_source in input_sources:
        input_type = input_source.parse_input_type()
        try:
            name = input_source.parse_name()
        except ValueError:
            # A parameter without a name cannot be referenced from a template.
            continue
        path = f"{prefix}{name}"
        if input_type == "repeat":
            item = Group(path)
            _add_inputs(
                item, input_source.parse_nested_inputs_source().parse_input_sources(), f"{path}.", tool_sanitize
            )
            group.add(name, Repeat(path, item))
        elif input_type == "section":
            section = Group(path)
            _add_inputs(
                section, input_source.parse_nested_inputs_source().parse_input_sources(), f"{path}.", tool_sanitize
            )
            group.add(name, section)
        elif input_type == "conditional":
            test_source = input_source.parse_test_input_source()
            conditional = Group(path, selector=test_source.parse_name())
            _add_inputs(conditional, [test_source], f"{path}.", tool_sanitize)
            values = []
            for value_name, case_source in input_source.parse_when_input_sources():
                values.append(str(value_name))
                case = Group(path)
                _add_inputs(case, case_source.parse_input_sources(), f"{path}.", tool_sanitize)
                for child_name, nodes in case.children.items():
                    for node in nodes:
                        conditional.add(child_name, node)
                        conditional.cases[node] = str(value_name)
            conditional.case_values = frozenset(values)
            group.add(name, conditional)
        elif input_type == "param":
            group.add(name, _value(input_source, path, tool_sanitize))
            if (input_source.get("type") or "") in ("data", "hidden_data"):
                # Galaxy adds the dataset converted for a <conversion> next to the parameter.
                for conversion, _ in input_source.parse_conversion_tuples():
                    if conversion and conversion not in group.children:
                        group.add(conversion, Data(f"{prefix}{conversion}", sanitize=tool_sanitize))


def build_model(tool_source: ToolSource) -> Model:
    tool_sanitize = bool(tool_source.parse_sanitize())
    root = Group("")
    for page_source in tool_source.parse_input_pages().page_sources:
        _add_inputs(root, page_source.parse_input_sources(), "", tool_sanitize)
    model = Model(root=root, sanitize=tool_sanitize)

    xml_tree: Any = getattr(tool_source, "xml_tree", None)
    if xml_tree is not None:
        model.templates = {name: text or "" for name, text in template_macro_params(xml_tree.getroot()).items()}
        for elem in xml_tree.findall("./outputs/data"):
            if elem.get("name") and elem.get("name") not in root.children:
                root.add(elem.get("name"), Data(elem.get("name"), output=True))
        for elem in xml_tree.findall("./outputs/collection"):
            if elem.get("name") and elem.get("name") not in root.children:
                root.add(elem.get("name"), Collection(elem.get("name"), output=True))
    for configfile in tool_source.parse_template_configfiles():
        if configfile.name:
            model.configfiles[configfile.name] = configfile.content or ""
            if configfile.name not in root.children:
                root.add(configfile.name, Special(f"configfile:{configfile.name}"))
    # Paths of the files Galaxy writes itself: the job's inputs as JSON, the file sources config.
    generated = [c.name for c in tool_source.parse_input_configfiles()]
    generated += [c.name for c in tool_source.parse_file_sources()]
    for name in generated:
        if name and name not in root.children:
            root.add(name, Special(name))

    for name in _SAFE_SPECIALS:
        model.specials[name] = Special(name)
    for name in _USER_SPECIALS:
        chars = DEFAULT_SANITIZED if tool_sanitize else PROBE
        model.specials[name] = Special(name, value=tainted(chars, source(f"${name}", SPECIAL, key=name)))
    model.specials["__user__"] = Special(
        "__user__", opaque=tainted(PROBE, source("attribute of the $__user__ object (not sanitized)", OPAQUE))
    )
    model.specials["__app__"] = Special("__app__", opaque=CLEAN)
    return model
