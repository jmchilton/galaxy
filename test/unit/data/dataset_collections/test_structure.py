from dataclasses import dataclass

import pytest

from galaxy.model.dataset_collections.structure import (
    get_structure,
    leaf,
    tool_output_to_structure,
)
from galaxy.model.dataset_collections.type_description import CollectionTypeDescriptionFactory
from galaxy.tool_util.parser.output_objects import (
    ToolOutput,
    ToolOutputCollection,
    ToolOutputCollectionStructure,
)
from .test_matching import (
    list_instance,
    list_of_lists_instance,
    list_of_paired_and_unpaired_instance,
    list_paired_instance,
    pair_instance,
)

factory = CollectionTypeDescriptionFactory(None)


@dataclass
class CollectionsManager:
    collection_type_descriptions: CollectionTypeDescriptionFactory


collections_manager = CollectionsManager(factory)


def test_get_structure_simple():
    paired_type_description = factory.for_collection_type("paired")
    tree = get_structure(pair_instance().collection, paired_type_description)
    assert len(tree.children) == 2
    assert tree.children[0][0] == "left"  # why not forward?
    assert tree.children[0][1].is_leaf


def test_get_structure_list_paired_over_paired():
    paired_type_description = factory.for_collection_type("list:paired")
    tree = get_structure(list_paired_instance().collection, paired_type_description, "paired")
    assert tree.collection_type_description.collection_type == "list"
    assert len(tree.children) == 3
    assert tree.children[0][0] == "data1"
    assert tree.children[0][1].is_leaf


def test_get_structure_list_of_lists():
    list_of_lists_type_description = factory.for_collection_type("list:list")
    tree = get_structure(list_of_lists_instance().collection, list_of_lists_type_description)
    assert tree.collection_type_description.collection_type == "list:list"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "outer1"
    assert not tree.children[0][1].is_leaf


def test_get_structure_list_of_lists_over_list():
    list_of_lists_type_description = factory.for_collection_type("list:list")
    tree = get_structure(list_of_lists_instance().collection, list_of_lists_type_description, "list")
    assert tree.collection_type_description.collection_type == "list"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "outer1"
    assert tree.children[0][1].is_leaf


def test_get_structure_list_paired_or_unpaired():
    list_pair_or_unpaired_description = factory.for_collection_type("list:paired_or_unpaired")
    tree = get_structure(list_of_paired_and_unpaired_instance().collection, list_pair_or_unpaired_description)
    assert tree.collection_type_description.collection_type == "list:paired_or_unpaired"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "el1"
    assert not tree.children[0][1].is_leaf


def test_get_structure_list_paired_or_unpaired_over_paired_or_unpaired():
    list_pair_or_unpaired_description = factory.for_collection_type("list:paired_or_unpaired")
    tree = get_structure(
        list_of_paired_and_unpaired_instance().collection, list_pair_or_unpaired_description, "paired_or_unpaired"
    )
    assert tree.collection_type_description.collection_type == "list"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "el1"
    assert tree.children[0][1].is_leaf


def test_tree_compatible_shape_sample_sheet_list_symmetric():
    """Tree.compatible_shape must be symmetric and shape-only.

    By the time matching runs (matching.py:65, execute.py:575) both sides
    have already passed connection-time edge validation. Two collections
    of equal shape and cardinality must match regardless of which sibling
    input was processed first as ``linked_structure``.
    """
    sample_sheet_td = factory.for_collection_type("sample_sheet")
    list_td = factory.for_collection_type("list")
    ss_tree = get_structure(list_instance(collection_type="sample_sheet").collection, sample_sheet_td)
    list_tree = get_structure(list_instance(collection_type="list").collection, list_td)
    assert ss_tree.compatible_shape(list_tree)
    assert list_tree.compatible_shape(ss_tree)


def test_tree_compatible_shape_sample_sheet_paired_list_paired_symmetric():
    """Same symmetry one rank deeper."""
    ss_paired_td = factory.for_collection_type("sample_sheet:paired")
    list_paired_td = factory.for_collection_type("list:paired")
    ss = list_paired_instance()
    ss.collection.collection_type = "sample_sheet:paired"
    ss_tree = get_structure(ss.collection, ss_paired_td)
    list_tree = get_structure(list_paired_instance().collection, list_paired_td)
    assert ss_tree.compatible_shape(list_tree)
    assert list_tree.compatible_shape(ss_tree)


def test_get_structure_list_of_lists_over_single_datasests():
    list_of_lists_type_description = factory.for_collection_type("list:list")
    tree = get_structure(list_of_lists_instance().collection, list_of_lists_type_description, "single_datasets")
    assert tree.collection_type_description.collection_type == "list:list"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "outer1"
    assert not tree.children[0][1].is_leaf


def _collection_output(**structure_kwds):
    return ToolOutputCollection("output", structure=ToolOutputCollectionStructure(**structure_kwds))


def _sliced_structures(**structures):
    return structures.__getitem__


def test_tool_output_to_structure_dataset_output():
    tree = tool_output_to_structure(_sliced_structures(), ToolOutput("output"), collections_manager)
    assert tree is leaf


def test_tool_output_to_structure_fixed_collection_type():
    tool_output = _collection_output(collection_type="list:paired")
    tree = tool_output_to_structure(_sliced_structures(), tool_output, collections_manager)
    assert not tree.children_known
    assert tree.collection_type_description.collection_type == "list:paired"


@pytest.mark.parametrize(
    "instance, collection_type",
    [
        (pair_instance, "paired"),
        (list_paired_instance, "list:paired"),
        (lambda: list_instance("sample_sheet"), "sample_sheet"),
    ],
)
def test_tool_output_to_structure_type_source(instance, collection_type):
    sliced = get_structure(instance().collection, factory.for_collection_type(collection_type))
    tool_output = _collection_output(collection_type=None, collection_type_source="input")
    tree = tool_output_to_structure(_sliced_structures(input=sliced), tool_output, collections_manager)
    assert not tree.children_known
    assert tree.collection_type_description.collection_type == collection_type


def test_tool_output_to_structure_type_source_multiplied_by_mapping_structure():
    list_paired_description = factory.for_collection_type("list:paired")
    mapping_structure = get_structure(list_paired_instance().collection, list_paired_description, "paired")
    sliced_pair = get_structure(pair_instance().collection, factory.for_collection_type("paired"))
    tool_output = _collection_output(collection_type=None, collection_type_source="input")
    tree = tool_output_to_structure(_sliced_structures(input=sliced_pair), tool_output, collections_manager)
    mapped = mapping_structure.multiply(tree)
    assert mapped.collection_type_description.collection_type == "list:paired"
    assert [identifier for identifier, _ in mapped.children] == ["data1", "data2", "data3"]


def test_tool_output_to_structure_structured_like():
    sliced_list = get_structure(list_instance().collection, factory.for_collection_type("list"))
    tool_output = _collection_output(collection_type=None, structured_like="input")
    tree = tool_output_to_structure(_sliced_structures(input=sliced_list), tool_output, collections_manager)
    assert tree is sliced_list


def test_tool_output_to_structure_type_overrides_structured_like():
    sliced_list = get_structure(list_instance().collection, factory.for_collection_type("list"))
    tool_output = _collection_output(collection_type="paired", structured_like="input")
    tree = tool_output_to_structure(_sliced_structures(input=sliced_list), tool_output, collections_manager)
    assert not tree.children_known
    assert tree.collection_type_description.collection_type == "paired"


def test_tool_output_to_structure_without_type_fails():
    tool_output = _collection_output(collection_type=None, collection_type_from_rules="rules")
    with pytest.raises(Exception, match="Failed to determine collection type"):
        tool_output_to_structure(_sliced_structures(), tool_output, collections_manager)


def test_tool_output_to_structure_type_source_prefix():
    sliced = get_structure(pair_instance().collection, factory.for_collection_type("paired"))
    tool_output = _collection_output(
        collection_type=None, collection_type_source="input", collection_type_prefix="list"
    )
    tree = tool_output_to_structure(_sliced_structures(input=sliced), tool_output, collections_manager)
    assert not tree.children_known
    assert tree.collection_type_description.collection_type == "list:paired"


def test_tool_output_to_structure_type_source_prefix_multiplied_by_mapping_structure():
    list_paired_description = factory.for_collection_type("list:paired")
    mapping_structure = get_structure(list_paired_instance().collection, list_paired_description, "paired")
    sliced_pair = get_structure(pair_instance().collection, factory.for_collection_type("paired"))
    tool_output = _collection_output(
        collection_type=None, collection_type_source="input", collection_type_prefix="list"
    )
    tree = tool_output_to_structure(_sliced_structures(input=sliced_pair), tool_output, collections_manager)
    mapped = mapping_structure.multiply(tree)
    assert mapped.collection_type_description.collection_type == "list:list:paired"
    assert [identifier for identifier, _ in mapped.children] == ["data1", "data2", "data3"]


def test_tool_output_to_structure_type_source_prefix_normalizes_sample_sheet():
    sliced = get_structure(list_instance("sample_sheet").collection, factory.for_collection_type("sample_sheet"))
    tool_output = _collection_output(
        collection_type=None, collection_type_source="input", collection_type_prefix="list"
    )
    tree = tool_output_to_structure(_sliced_structures(input=sliced), tool_output, collections_manager)
    assert tree.collection_type_description.collection_type == "list:list"
