import pytest

from galaxy.model.dataset_collections.structure import (
    get_structure,
    leaf,
    Tree,
    UninitializedTree,
)
from galaxy.model.dataset_collections.type_description import CollectionTypeDescriptionFactory
from .test_matching import (
    list_of_lists_instance,
    list_of_paired_and_unpaired_instance,
    list_paired_instance,
    pair_instance,
)

factory = CollectionTypeDescriptionFactory(None)


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


def test_get_structure_list_of_lists_over_single_datasests():
    list_of_lists_type_description = factory.for_collection_type("list:list")
    tree = get_structure(list_of_lists_instance().collection, list_of_lists_type_description, "single_datasets")
    assert tree.collection_type_description.collection_type == "list:list"
    assert len(tree.children) == 2
    assert tree.children[0][0] == "outer1"
    assert not tree.children[0][1].is_leaf


COLUMN_DEFINITIONS = [{"name": "condition", "type": "string", "optional": False}]
COLUMNS_METADATA = {"sample1": ["treated"], "sample2": ["control"]}


def _sample_sheet_tree(collection_type="sample_sheet"):
    child = leaf
    if collection_type == "sample_sheet:paired":
        child = Tree([("forward", leaf), ("reverse", leaf)], factory.for_collection_type("paired"))
    return Tree(
        [("sample1", child), ("sample2", child)],
        factory.for_collection_type(collection_type),
        columns_metadata=COLUMNS_METADATA,
        column_definitions=COLUMN_DEFINITIONS,
    )


def _uninitialized(collection_type):
    return UninitializedTree(factory.for_collection_type(collection_type))


@pytest.mark.parametrize(
    "mapping_type,output_structure,expected_type",
    [
        ("sample_sheet", leaf, "sample_sheet"),
        ("sample_sheet", _uninitialized("paired"), "sample_sheet:paired"),
        ("sample_sheet", _uninitialized("record"), "sample_sheet:record"),
        ("sample_sheet", _uninitialized("paired_or_unpaired"), "sample_sheet:paired_or_unpaired"),
        ("sample_sheet:paired", leaf, "sample_sheet:paired"),
    ],
)
def test_multiply_sample_sheet_keeps_columns(mapping_type, output_structure, expected_type):
    mapped = _sample_sheet_tree(mapping_type).multiply(output_structure)
    assert mapped.collection_type_description.collection_type == expected_type
    assert mapped.column_definitions == COLUMN_DEFINITIONS
    assert mapped.columns_metadata == COLUMNS_METADATA


@pytest.mark.parametrize(
    "mapping_type,output_structure,expected_type",
    [
        ("sample_sheet", _uninitialized("list"), "list:list"),
        ("sample_sheet", _uninitialized("list:paired"), "list:list:paired"),
        ("sample_sheet:paired", _uninitialized("list"), "list:paired:list"),
        # unlinked (cross product) batch inputs multiply two known structures
        ("sample_sheet", Tree([("a", leaf), ("b", leaf)], factory.for_collection_type("list")), "list:list"),
    ],
)
def test_multiply_sample_sheet_by_nested_collection_demotes_to_list(mapping_type, output_structure, expected_type):
    mapped = _sample_sheet_tree(mapping_type).multiply(output_structure)
    assert mapped.collection_type_description.collection_type == expected_type
    assert [identifier for identifier, _ in mapped.children] == ["sample1", "sample2"]
    # a plain list cannot carry sample sheet columns
    assert mapped.column_definitions is None
    assert mapped.columns_metadata == {}
