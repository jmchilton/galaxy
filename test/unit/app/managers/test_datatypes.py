from dataclasses import (
    dataclass,
    field,
)

from galaxy.datatypes.registry import example_datatype_registry_for_sample
from galaxy.managers.datatypes import (
    get_preferred_visualization,
    view_converters,
)


def test_preferred_visualization_direct_mapping():
    registry = example_datatype_registry_for_sample()
    mapping = get_preferred_visualization(registry, "hyphy_results.json")
    assert mapping
    assert mapping["visualization"] == "hyphyvision"


def test_preferred_visualization_not_inherited_by_sibling_subclass():
    registry = example_datatype_registry_for_sample()
    for extension in ("anvio_state", "freq.json", "hivtrace"):
        assert get_preferred_visualization(registry, extension) is None


def test_preferred_visualization_inherited_from_parent_datatype():
    registry = example_datatype_registry_for_sample()
    for extension, visualization in (("mbi", "h5web"), ("ome.tiff", "tiffviewer"), ("probam", "igv")):
        mapping = get_preferred_visualization(registry, extension)
        assert mapping
        assert mapping["visualization"] == visualization


@dataclass(eq=False)
class _StubConverter:
    id: str
    license_agreements: list[object] = field(default_factory=list)


def test_view_converters_excludes_converters_requiring_license_agreements():
    registry = example_datatype_registry_for_sample()
    registry._register_converter_tool(_StubConverter("to_tabular", license_agreements=[object()]), "fasta", "tabular")
    registry._register_converter_tool(_StubConverter("to_txt"), "fasta", "txt")

    listed = {c.target: c.tool_id for c in view_converters(registry).root if c.source == "fasta"}
    assert "tabular" not in listed
    assert listed["txt"] == "to_txt"
