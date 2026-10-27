"""Resolve output references (e.g. ``format_source``) against declared tool inputs."""

import re
from typing import (
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


class InputReferences:
    """Input parameter paths as runtime keys them, with repeat indices normalized to ``_0``.

    ``qualified`` includes every conditional, section and repeat. ``legacy`` is the alias
    ``visit_input_values`` also records, which omits only the innermost conditional or
    section name.
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
            elif input_type not in ("conditional", "section", "repeat") or (name := input_source.get("name")) is None:
                continue
            elif input_type == "conditional":
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
        segments = []
        for segment in reference.split("|"):
            base, _, index = segment.rpartition("_")
            if index.isdigit() and base in self.repeat_names:
                segment = f"{base}_0"
            segments.append(segment)
        return "|".join(segments)

    def qualified(self, reference: str) -> list[InputReference]:
        return [r for r in self.references if r.qualified == reference]

    def candidates(self, reference: str) -> list[str]:
        name = reference.rsplit("|", 1)[-1]
        return sorted({r.qualified for r in self.references if r.name == name})

    def resolve(self, reference: str) -> ResolvedReference:
        """Match a reference to declared inputs, preferring a qualified path over a legacy alias."""
        path, selector = split_element_selector(reference)
        normalized = self.normalize(path)
        matches = self.qualified(normalized)
        legacy = not matches
        if legacy:
            matches = [r for r in self.references if r.legacy == normalized]
        return ResolvedReference(reference, path, selector, matches, legacy)
