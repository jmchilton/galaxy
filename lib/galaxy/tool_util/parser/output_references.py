"""Resolve output references (``format_source``, ``metadata_source``) against declared tool inputs."""

import re
from typing import (
    Literal,
    NamedTuple,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from .interface import (
        InputSource,
        PageSource,
        ToolSource,
    )

# A single element selector on a collection input, e.g. input_collection['forward'].
ELEMENT_SELECTOR = re.compile(r"^([^\[\]]*)\[[^\[\]]*\]$")


def split_element_selector(reference: str) -> tuple[str, str]:
    """Split ``coll['forward']`` into ``("coll", "['forward']")``; the selector is empty if absent."""
    if selector_match := ELEMENT_SELECTOR.match(reference):
        path = selector_match.group(1)
        return path, reference[len(path) :]
    return reference, ""


class InputReference(NamedTuple):
    qualified: str
    legacy: str
    param_type: str | None
    in_repeat: bool

    @property
    def is_collection(self) -> bool:
        return self.param_type == "data_collection"

    @property
    def name(self) -> str:
        return self.qualified.rsplit("|", 1)[-1]


class ResolvedReference(NamedTuple):
    reference: str
    path: str
    selector: str
    matches: list[InputReference]
    legacy: bool
    qualified_key: str | None
    """The qualified form of the reference, with its own repeat indices, when one input matches."""
    runtime_key: str
    """The key to look the reference up by at job runtime."""
    shadowed: bool = False
    """A legacy reference kept as written because its qualified key is another input's legacy alias."""


OutputReferenceAttribute = Literal["format_source", "metadata_source"]

# Tool profile from which an unresolvable or ambiguous output reference fails tool load.
OUTPUT_REFERENCE_STRICT_PROFILE = "27.0"

DATA_INPUT_TYPES = ("data", "hidden_data", "data_collection")

# Input types each output reference attribute can name; only format_source reads collections.
OUTPUT_REFERENCE_PARAM_TYPES: dict[OutputReferenceAttribute, tuple[str, ...]] = {
    "format_source": DATA_INPUT_TYPES,
    "metadata_source": ("data", "hidden_data"),
}


def output_reference_problem(resolved: ResolvedReference, attribute: OutputReferenceAttribute) -> str | None:
    """Why job runtime cannot resolve an output reference, or ``None`` if it can."""
    param_types = OUTPUT_REFERENCE_PARAM_TYPES[attribute]
    if not resolved.matches:
        return "does not match any declared input"
    if not any(r.param_type in param_types for r in resolved.matches):
        return f"must name a {', '.join(param_types[:-1])} or {param_types[-1]} input"
    if resolved.selector and (attribute != "format_source" or not any(r.is_collection for r in resolved.matches)):
        return "selects an element of an input that is not a collection"
    return None


def output_reference_ambiguity(resolved: ResolvedReference) -> str | None:
    """Why a legacy reference is ambiguous at job runtime, or ``None`` if it is not."""
    if resolved.shadowed:
        return f"is ambiguous. Use the qualified name '{resolved.qualified_key}'"
    return None


class InputReferences:
    """Input parameter paths as runtime keys them, with repeat indices normalized to ``_0``.

    ``legacy`` is the ``visit_input_values`` alias, omitting the innermost conditional or section name.
    """

    def __init__(self, tool_source: "ToolSource") -> None:
        self.references: list[InputReference] = []
        self.repeat_names: set[str] = set()
        pages = tool_source.parse_input_pages()
        if pages.inputs_defined:
            for page_source in pages.page_sources:
                self._visit(page_source, [], [], False)

    def _visit(self, page_source: "PageSource", qualified: list[str], legacy: list[str], in_repeat: bool) -> None:
        for input_source in page_source.parse_input_sources():
            input_type = input_source.parse_input_type()
            if input_type == "param":
                self._add_param(input_source, qualified, legacy, in_repeat)
                continue
            name = input_source.get("name")
            if name is None:
                continue
            if input_type == "conditional":
                # A value_from conditional has no test param.
                if not input_source.get("value_from"):
                    self._add_param(input_source.parse_test_input_source(), qualified + [name], qualified, in_repeat)
                for _, case_page_source in input_source.parse_when_input_sources():
                    self._visit(case_page_source, qualified + [name], qualified, in_repeat)
            elif input_type == "section":
                self._visit(input_source.parse_nested_inputs_source(), qualified + [name], qualified, in_repeat)
            elif input_type == "repeat":
                self.repeat_names.add(name)
                path = qualified + [f"{name}_0"]
                self._visit(input_source.parse_nested_inputs_source(), path, path, True)

    def _add_param(self, input_source: "InputSource", qualified: list[str], legacy: list[str], in_repeat: bool) -> None:
        try:
            name = input_source.parse_name()
        except ValueError:
            return
        self.references.append(
            InputReference(
                "|".join(qualified + [name]),
                "|".join(legacy + [name]),
                input_source.get("type"),
                in_repeat,
            )
        )

    def normalize(self, reference: str) -> str:
        return "|".join(
            f"{segment.rpartition('_')[0]}_0" if self._is_repeat_segment(segment) else segment
            for segment in reference.split("|")
        )

    def _is_repeat_segment(self, segment: str) -> bool:
        base, _, index = segment.rpartition("_")
        return index.isdigit() and base in self.repeat_names

    def qualified(self, reference: str) -> list[InputReference]:
        return [r for r in self.references if r.qualified == reference]

    def candidates(self, reference: str) -> list[str]:
        name = reference.rsplit("|", 1)[-1]
        return sorted({r.qualified for r in self.references if r.name == name})

    def resolve(self, reference: str) -> ResolvedReference:
        """Match a reference to declared inputs, preferring a qualified path over a legacy alias."""
        path, selector = split_element_selector(reference)
        normalized = self.normalize(path)
        # An exact match first, so a parameter named like a repeat instance (rep_1) isn't normalized away.
        matches = self.qualified(path) or self.qualified(normalized)
        legacy = not matches
        if legacy:
            matches = [r for r in self.references if r.legacy == normalized]
        qualified_key = None
        runtime_key = reference
        shadowed = False
        qualified_names = {r.qualified for r in matches}
        if len(qualified_names) == 1:
            (qualified,) = qualified_names
            reindexed = self._reindex(qualified, path)
            if reindexed is not None:
                qualified_key = reindexed + selector
                # Job creation keys (expanded multiple inputs, conversions) can shadow a legacy alias; skip if ambiguous.
                if legacy:
                    shadowed = self._is_other_legacy_alias(qualified)
                    if not shadowed:
                        runtime_key = qualified_key
        return ResolvedReference(reference, path, selector, matches, legacy, qualified_key, runtime_key, shadowed)

    def _is_other_legacy_alias(self, qualified: str) -> bool:
        return any(r.legacy == qualified and r.qualified != qualified for r in self.references)

    def _reindex(self, qualified: str, path: str) -> str | None:
        # A legacy alias drops conditional and section names but keeps every repeat segment, in order.
        indices = [segment for segment in path.split("|") if self._is_repeat_segment(segment)]
        segments = qualified.split("|")
        if len(indices) != sum(self._is_repeat_segment(segment) for segment in segments):
            return None
        indexed = iter(indices)
        return "|".join(next(indexed) if self._is_repeat_segment(segment) else segment for segment in segments)
