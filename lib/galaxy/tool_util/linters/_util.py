import re
from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from galaxy.util.etree import (
        Element,
        ElementTree,
    )

ParamQualifiedPaths = dict[str, list[str]]


def is_datasource(tool_xml):
    """Returns true if the tool is a datasource tool"""
    return tool_xml.getroot().attrib.get("tool_type", "") in ["data_source", "data_source_async"]


def is_valid_cheetah_placeholder(name):
    """Returns true if name is a valid Cheetah placeholder"""
    return re.match(r"^[a-zA-Z_]\w*$", name) is not None


def iter_output_input_references(
    tool_xml: "ElementTree", output_xpaths: list[str], attr_name: str
) -> Iterator[tuple["Element", str, list[str] | None]]:
    """Yield ``(output, reference, matches)`` for outputs referencing an input by ``attr_name``.

    ``matches`` lists the qualified paths an unqualified reference to a nested input could mean,
    and is ``None`` when the reference is qualified or names a top-level input.
    """
    param_qualified_paths = _collect_param_qualified_paths(tool_xml)
    for output_xpath in output_xpaths:
        for output in tool_xml.findall(f"{output_xpath}[@{attr_name}]"):
            reference = output.attrib[attr_name]
            yield output, reference, _unqualified_nested_matches(reference, param_qualified_paths)


def _unqualified_nested_matches(ref_value: str, param_qualified_paths: ParamQualifiedPaths) -> list[str] | None:
    """Qualified paths an unqualified reference could mean; ``None`` if qualified or naming a top-level param."""
    if "|" in ref_value:
        return None
    if any(qp == ref_value for paths in param_qualified_paths.values() for qp in paths):
        return None
    return param_qualified_paths.get(ref_value, [])


def _collect_param_qualified_paths(tool_xml: "ElementTree") -> ParamQualifiedPaths:
    """Build a map of unqualified param name -> list of qualified paths."""
    param_paths: ParamQualifiedPaths = {}
    parent_map = {child: parent for parent in tool_xml.iter() for child in parent}
    for param in tool_xml.findall("./inputs//param"):
        name = param.attrib.get("name")
        if not name:
            argument = param.attrib.get("argument")
            if argument:
                name = argument.lstrip("-").replace("-", "_")
        if not name:
            continue
        qualified = _get_qualified_name(param, parent_map)
        param_paths.setdefault(name, []).append(qualified)
    return param_paths


def _get_qualified_name(param_elem: "Element", parent_map: dict["Element", "Element"]) -> str:
    """Walk up the XML tree to build the qualified path for a param element."""
    name = param_elem.attrib.get("name")
    if not name:
        argument = param_elem.attrib.get("argument")
        if argument:
            name = argument.lstrip("-").replace("-", "_")
    parts = [name] if name else []
    current = param_elem
    while True:
        parent = parent_map.get(current)
        if parent is None:
            break
        if parent.tag in ("conditional", "section"):
            parent_name = parent.attrib.get("name")
            if parent_name:
                parts.insert(0, parent_name)
        elif parent.tag in ("inputs", "tool"):
            break
        current = parent
    return "|".join(parts)
