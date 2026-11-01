from typing import Any

import pytest

from galaxy import exceptions
from galaxy.model.dataset_collections.subcollections import _split_dataset_collection
from .test_matching import (
    collection_element,
    list_element,
    list_instance,
    list_paired_instance,
)


def list_of_lists():
    return list_instance(collection_type="list:list", elements=[list_element("outer1"), list_element("outer2")])


def list_of_lists_of_pairs():
    return list_instance(
        collection_type="list:list:paired",
        elements=[collection_element("outer1", list_paired_instance().collection)],
    )


def split_identifiers(collection, collection_type: str) -> list[str]:
    elements: list[Any] = _split_dataset_collection(collection, collection_type)
    return [e.element_identifier for e in elements]


def test_split_list_of_lists_over_list():
    assert split_identifiers(list_of_lists().collection, "list") == ["outer1", "outer2"]


def test_split_list_of_lists_over_list_paired_or_unpaired():
    assert split_identifiers(list_of_lists().collection, "list:paired_or_unpaired") == ["outer1", "outer2"]


def test_split_list_of_lists_of_pairs_over_list_paired_or_unpaired():
    assert split_identifiers(list_of_lists_of_pairs().collection, "list:paired_or_unpaired") == ["outer1"]


def test_split_list_paired_over_list_paired_or_unpaired_fails():
    # a direct match, not a map over
    with pytest.raises(exceptions.MessageException):
        _split_dataset_collection(list_paired_instance().collection, "list:paired_or_unpaired")


@pytest.mark.parametrize("collection_type", ["sample_sheet", "sample_sheet:paired_or_unpaired"])
def test_split_list_of_lists_over_sample_sheet_fails(collection_type):
    with pytest.raises(exceptions.MessageException):
        _split_dataset_collection(list_of_lists().collection, collection_type)
