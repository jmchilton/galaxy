"""Collection-type handling in ``DataCollectionToolParameter.from_json``."""

from dataclasses import dataclass
from typing import Any

import pytest

from galaxy import model
from galaxy.tools.parameters.basic import (
    DataCollectionToolParameter,
    workflow_building_modes,
)
from galaxy.util import parse_xml_string


def _param(collection_type=None):
    type_attribute = f'collection_type="{collection_type}"' if collection_type else ""
    return DataCollectionToolParameter(
        None, parse_xml_string(f'<param name="input" type="data_collection" {type_attribute}/>')
    )


def _hda():
    hda = model.HistoryDatasetAssociation(extension="txt", dataset=model.Dataset())
    hda.dataset.state = model.Dataset.states.OK
    return hda


def _collection(collection_type):
    """Build a populated collection with two elements at every level."""
    collection = model.DatasetCollection(collection_type=collection_type, populated=True)
    rank_type, _, child_type = collection_type.partition(":")
    identifiers = ["forward", "reverse"] if rank_type == "paired" else ["a", "b"]
    for index, identifier in enumerate(identifiers):
        element = _collection(child_type) if child_type else _hda()
        model.DatasetCollectionElement(
            collection=collection, element=element, element_index=index, element_identifier=identifier
        )
    return collection


def _hdca(collection_type):
    return model.HistoryDatasetCollectionAssociation(collection=_collection(collection_type), deleted=False)


@dataclass
class _Trans:
    """The trans attributes ``from_json`` reads when given model objects directly."""

    sa_session: Any = None
    security: Any = None
    workflow_building_mode: Any = workflow_building_modes.DISABLED
    history: Any = None


def _trans():
    return _Trans()


@pytest.mark.parametrize(
    "accepts,supplied",
    [
        ("list", "list"),
        ("paired", "paired"),
        ("list,list:paired", "list:paired"),
        ("list", "sample_sheet"),
        ("list:paired", "sample_sheet:paired"),
        ("paired_or_unpaired", "paired"),
        ("paired_or_unpaired", "paired_or_unpaired"),
        ("list:paired_or_unpaired", "list"),
        ("list:paired_or_unpaired", "list:paired"),
        (None, "paired"),
        (None, "list:list"),
    ],
)
def test_from_json_accepts_compatible_hdca(accepts, supplied):
    hdca = _hdca(supplied)
    assert _param(accepts).from_json(hdca, _trans()) is hdca
