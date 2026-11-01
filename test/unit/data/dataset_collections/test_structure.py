import pytest

from galaxy.managers.collections import DatasetCollectionManager
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


def _sample_sheet_tree(collection_type="sample_sheet"):
    child = leaf
    if collection_type == "sample_sheet:paired":
        child = Tree([("forward", leaf), ("reverse", leaf)], factory.for_collection_type("paired"))
    return Tree(
        [("sample1", child), ("sample2", child)],
        factory.for_collection_type(collection_type),
        columns_metadata={"sample1": ["treated"], "sample2": ["control"]},
        column_definitions=COLUMN_DEFINITIONS,
    )


def _precreate(structure):
    # precreate_dataset_collection needs no app or session for an unpersisted structure.
    manager = object.__new__(DatasetCollectionManager)
    return manager.precreate_dataset_collection(structure)


def test_multiply_sample_sheet_by_dataset_output():
    mapped = _sample_sheet_tree().multiply(leaf)
    assert mapped.collection_type_description.collection_type == "sample_sheet"
    mapped.collection_type_description.validate()
    collection = _precreate(mapped)
    assert collection.collection_type == "sample_sheet"
    assert collection.column_definitions == COLUMN_DEFINITIONS
    assert [e.columns for e in collection.elements] == [["treated"], ["control"]]


@pytest.mark.parametrize("output_type", ["paired", "record", "paired_or_unpaired"])
def test_multiply_sample_sheet_by_valid_sample_sheet_suffix_output(output_type):
    mapped = _sample_sheet_tree().multiply(UninitializedTree(factory.for_collection_type(output_type)))
    expected_type = f"sample_sheet:{output_type}"
    assert mapped.collection_type_description.collection_type == expected_type
    mapped.collection_type_description.validate()
    collection = _precreate(mapped)
    assert collection.collection_type == expected_type
    assert collection.column_definitions == COLUMN_DEFINITIONS
    assert [e.columns for e in collection.elements] == [["treated"], ["control"]]


def test_multiply_sample_sheet_paired_by_dataset_output():
    mapped = _sample_sheet_tree("sample_sheet:paired").multiply(leaf)
    assert mapped.collection_type_description.collection_type == "sample_sheet:paired"
    collection = _precreate(mapped)
    assert collection.column_definitions == COLUMN_DEFINITIONS
    assert [e.columns for e in collection.elements] == [["treated"], ["control"]]
