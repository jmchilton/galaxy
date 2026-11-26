"""The objects Galaxy puts into a template's namespace, as the analysis sees them.

The semantics mirror the wrappers in ``galaxy.tools.wrappers``: the same parameter gives a
sanitized string when written as ``$param`` and the raw submitted value through ``$param.value``
or a string method; a dataset gives its path, its name, its metadata.
"""

from __future__ import annotations

import ast
from dataclasses import (
    dataclass,
    field,
    replace,
)
from typing import Iterator

from .charsets import (
    default_chars,
    PROBE,
)
from .report import (
    DATASET_ATTRIBUTE,
    DATASET_CONTENT,
    ELEMENT_IDENTIFIER,
    GROUP_TAGS,
    METADATA,
    OPAQUE,
    RAW_DATASET_ATTRIBUTE,
    RAW_METADATA,
    source_refs,
    SourceRef,
    SPECIAL,
    USER_PREFERENCE,
)
from .values import (
    AV,
    CLEAN,
    contents,
    join,
    Node,
    returns_receiver,
    source,
    stringify,
    tainted,
)


@dataclass(eq=False)
class Value(Node):
    """A parameter whose value is text: text, select, column, tag, number, boolean..."""

    path: str
    type: str
    as_text: AV = CLEAN
    as_raw: AV = CLEAN
    as_element: AV | None = None
    text_like: bool = False  # unknown attributes are string methods of the raw value
    # A select that takes only these values, each rendered as it is: options fixed in the tool, no sanitizer.
    options: tuple[str, ...] | None = None

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

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        for value in (self.as_text, self.as_raw, self.as_element or CLEAN):
            yield from source_refs(value.sources)


@dataclass(eq=False)
class Opaque(Node):
    """An object whose every attribute, item and call result is the same kind of value."""

    path: str
    value: AV = CLEAN

    def text(self) -> AV:
        # The object is not the value it holds: its text is not the string the job check reads.
        return replace(self.value, verbatim=False)

    def attr(self, name: str) -> AV | None:
        return AV(chars=self.value.chars, sources=self.value.sources, nodes=(self,))

    def element(self) -> AV | None:
        return AV(chars=self.value.chars, sources=self.value.sources, nodes=(self,))

    def _beyond(self, name: str) -> AV:
        """An attribute that reaches other objects: opaque, whatever this node knows of its own."""
        return AV(
            chars=self.value.chars, sources=self.value.sources, nodes=(Opaque(f"{self.path}.{name}", self.value),)
        )


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


# Dataset attributes a template reads by name, which hold text a user chose.
_NAMED_ATTRIBUTES = ("info", "created_from_basename", "dbkey")


def dataset_sources(path: str, names: frozenset[str]) -> Iterator[SourceRef]:
    """What a template can read of the datasets of an input: identifiers and names always, other
    attributes, group tags and metadata when it names them (``key=None``: any metadata element)."""
    yield SourceRef(ELEMENT_IDENTIFIER, path)
    yield SourceRef(DATASET_ATTRIBUTE, path, "name")
    for attribute in _NAMED_ATTRIBUTES:
        if attribute in names:
            yield SourceRef(DATASET_ATTRIBUTE, path, attribute)
    if names & {"groups", "group", "group_tags"}:
        yield SourceRef(GROUP_TAGS, path)
    if "metadata" in names:
        yield SourceRef(METADATA, path)


@dataclass(eq=False)
class Data(Node):
    path: str
    multiple: bool = False
    sanitize: bool = True
    output: bool = False

    def _safe_string(self, what: str, accessor: str = DATASET_ATTRIBUTE, key: str | None = None) -> AV:
        # Attributes of the dataset go through SafeStringWrapper: Galaxy's default sanitizer.
        return tainted(
            default_chars(self.sanitize),
            source(f"{what} of dataset '{self.path}'", accessor, self.path, key),
        )

    def attr(self, name: str) -> AV | None:
        if self.output:
            return CLEAN
        if name in ("element_identifier", "name_and_ext"):
            return tainted(
                PROBE,
                source(f"element identifier of dataset '{self.path}' (not sanitized)", ELEMENT_IDENTIFIER, self.path),
                # name_and_ext adds the extension to the identifier the job check reads.
                verbatim=name == "element_identifier",
            )
        if name == "groups":
            return AV(
                elem=tainted(
                    PROBE, source(f"group tags of dataset '{self.path}' (not sanitized)", GROUP_TAGS, self.path)
                )
            )
        if name == "get_staging_path":
            staged = source(f"element identifier of dataset '{self.path}'", ELEMENT_IDENTIFIER, self.path)
            return AV(bound=(tainted(PROBE - {"/"}, staged), returns_receiver))
        if name == "metadata":
            return AV(nodes=(Metadata(self.path, self),))
        if name == "unsanitized":
            raw_model = source(f"raw model of dataset '{self.path}'", OPAQUE, self.path)
            return AV(nodes=(RawDataset(f"{self.path}.unsanitized", tainted(PROBE, raw_model), self.path),))
        if name == "dataset":
            return AV(nodes=(DatasetObject(self.path, self),))
        if name == "single_item":
            return AV(nodes=(self,))
        if name in _DATA_CLEAN:
            return CLEAN
        return self._safe_string("name" if name == "name" else f"attribute '{name}'", key=name)

    def element(self) -> AV | None:
        return AV(nodes=(self,))

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        return iter(()) if self.output else dataset_sources(self.path, names)


# Attributes of a dataset model that Galaxy sets itself: its type, its id, its paths and state.
_RAW_DATASET_CLEAN = frozenset(
    "ext extension id hid extra_files_path get_file_name file_name get_size has_data state".split()
)


# String attributes of a dataset model that users set: the job check reads them from the model too.
_RAW_DATASET_STRINGS = frozenset(("name", "info", "created_from_basename", "dbkey"))


@dataclass(eq=False)
class RawDataset(Opaque):
    """``$input.unsanitized``: the dataset model itself, whose strings are not sanitized.

    Its own strings and metadata are values of the job; anything else it reaches (its history, its
    tags, the job that made it) stays opaque."""

    data_path: str = ""

    def attr(self, name: str) -> AV | None:
        if name in _RAW_DATASET_CLEAN:
            return CLEAN
        if name == "metadata":
            return AV(nodes=(RawMetadata(f"{self.path}.metadata", self.value, self.data_path),))
        if name in _RAW_DATASET_STRINGS:
            return tainted(
                PROBE,
                source(
                    f"raw {name} of dataset '{self.data_path}' (not sanitized)",
                    RAW_DATASET_ATTRIBUTE,
                    self.data_path,
                    name,
                ),
                verbatim=True,
            )
        return self._beyond(name)


@dataclass(eq=False)
class RawMetadata(Opaque):
    """The metadata of a dataset model: Galaxy computes some of it from the file."""

    data_path: str = ""

    def attr(self, name: str) -> AV | None:
        if name in _METADATA_CLEAN or name.endswith(("_index", "Col")):
            return CLEAN
        if name.isidentifier() and not name.startswith("_") and name not in ("spec", "items", "get", "parent"):
            return tainted(
                PROBE,
                source(
                    f"raw metadata '{name}' of dataset '{self.data_path}' (not sanitized)",
                    RAW_METADATA,
                    self.data_path,
                    name,
                ),
            )
        return self._beyond(name)


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
            return AV(bound=(AV(elem=self._identifier()), returns_receiver))
        if name == "items":
            pair = AV(items=(self._identifier(), self.element() or CLEAN))
            return AV(bound=(AV(elem=pair), returns_receiver))
        if name == "values":
            return AV(bound=(AV(elem=self.element()), returns_receiver))
        if name == "get_datasets_for_group":
            # The datasets of the collection, at any depth, whose tags name the group.
            return AV(bound=(AV(elem=AV(nodes=(Data(self.path, sanitize=self.sanitize),))), returns_receiver))
        if name in ("element_identifiers_extensions_paths_and_metadata_files", "sample_sheet_row"):
            return AV(nodes=(Opaque(f"{self.path}.{name}", self._identifier()),))
        if name == "get_all_staging_paths":
            staged = tainted(
                PROBE - {"/"}, source(f"element identifier of collection '{self.path}'", ELEMENT_IDENTIFIER, self.path)
            )
            return AV(bound=(AV(elem=staged), returns_receiver))
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

    def sources(self, names: frozenset[str]) -> Iterator[SourceRef]:
        return iter(()) if self.output else dataset_sources(self.path, names)


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


def dataset_content(datasets: tuple[Data, ...]) -> AV:
    """What ``open()`` of an input dataset gives a template: its content, which the job check can read too."""
    contents = []
    for data in datasets:
        content = tainted(
            PROBE, source(f"content of dataset '{data.path}' (not sanitized)", DATASET_CONTENT, data.path)
        )
        contents.append(AV(nodes=(Opaque(f"{data.path} content", content),)))
    return join(*contents)


_USER_OBJECT = tainted(PROBE, source("attribute of the $__user__ object (not sanitized)", OPAQUE))


# The attributes of the user object that Galaxy also puts into the namespace as account values.
USER_ACCOUNT_ATTRIBUTES = {"email": "__user_email__", "username": "__user_name__"}


@dataclass(eq=False)
class User(Node):
    """``$__user__``: the user's model object. Its preferences are the user's to set."""

    path: str = "__user__"

    def text(self) -> AV:
        return CLEAN

    def attr(self, name: str) -> AV | None:
        if name == "extra_preferences":
            return AV(nodes=(UserPreferences("__user__.extra_preferences"),))
        if name in USER_ACCOUNT_ATTRIBUTES:
            key = USER_ACCOUNT_ATTRIBUTES[name]
            return tainted(PROBE, source(f"${key}", SPECIAL, key=key))
        return AV(nodes=(Opaque(f"__user__.{name}", _USER_OBJECT),))


_DICT_ATTRIBUTES = frozenset(dir(dict))


@dataclass(eq=False)
class UserPreferences(Opaque):
    """``$__user__.extra_preferences``: ``.get(name)``, ``[name]`` and ``.name`` are one preference."""

    value: AV = field(default_factory=lambda: _USER_OBJECT)

    def attr(self, name: str) -> AV | None:
        if name == "get":
            return AV(bound=(AV(nodes=(self,)), gets_preference))
        if name not in _DICT_ATTRIBUTES:
            # A subscript, or a Cheetah name that is not a dict method, reads the preference of that name.
            return user_preference(name)
        return super().attr(name)


def gets_preference(receiver: AV, args: list[AV], keywords: list[AV], nodes: list[ast.expr]) -> AV:
    """`$__user__.extra_preferences.get('name', default)`: that preference, or the default."""
    name = nodes[0].value if nodes and isinstance(nodes[0], ast.Constant) else None
    found = user_preference(name) if isinstance(name, str) else stringify(receiver)
    return join(found, *(contents(a) for a in args[1:] + keywords))


def user_preference(name: str) -> AV:
    return tainted(PROBE, source(f"user preference '{name}' (not sanitized)", USER_PREFERENCE, key=name))


def file_content() -> AV:
    """What ``open(path)`` gives a template: the content of a file, which is a dataset unless shown otherwise."""
    content = tainted(PROBE, source("content of a file the template reads with open() (not sanitized)", OPAQUE))
    return AV(nodes=(Opaque("open()", content),))
