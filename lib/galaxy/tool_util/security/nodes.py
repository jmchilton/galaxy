"""The objects Galaxy puts into a template's namespace, as the analysis sees them.

The semantics mirror the wrappers in ``galaxy.tools.wrappers``: the same parameter gives a
sanitized string when written as ``$param`` and the raw submitted value through ``$param.value``
or a string method; a dataset gives its path, its name, its metadata.
"""

from __future__ import annotations

from dataclasses import (
    dataclass,
    field,
)

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
    USER_PREFERENCE,
)
from .values import (
    AV,
    CLEAN,
    join,
    Node,
    source,
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


@dataclass(eq=False)
class User(Node):
    """``$__user__``: the user's model object. Its preferences are the user's to set."""

    path: str = "__user__"

    def text(self) -> AV:
        return CLEAN

    def attr(self, name: str) -> AV | None:
        if name == "extra_preferences":
            return AV(nodes=(UserPreferences("__user__.extra_preferences"),))
        return AV(nodes=(Opaque(f"__user__.{name}", _USER_OBJECT),))


@dataclass(eq=False)
class UserPreferences(Opaque):
    """``$__user__.extra_preferences``: ``.get(name)`` is one preference."""

    value: AV = field(default_factory=lambda: _USER_OBJECT)

    def attr(self, name: str) -> AV | None:
        if name == "get":
            return AV(bound=(AV(nodes=(self,)), "__preference__"))
        return super().attr(name)


def user_preference(name: str) -> AV:
    return tainted(PROBE, source(f"user preference '{name}' (not sanitized)", USER_PREFERENCE, key=name))


def file_content() -> AV:
    """What ``open(path)`` gives a template: the content of a file, which is a dataset unless shown otherwise."""
    content = tainted(PROBE, source("content of a file the template reads with open() (not sanitized)", OPAQUE))
    return AV(nodes=(Opaque("open()", content),))
