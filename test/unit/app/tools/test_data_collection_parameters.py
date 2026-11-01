"""Collection-type handling in ``DataCollectionToolParameter.from_json``."""

from dataclasses import dataclass
from typing import Any

import pytest

from galaxy import model
from galaxy.model.dataset_collections.adapters import PromoteCollectionElementToCollectionAdapter
from galaxy.tools.parameters.basic import (
    DataCollectionToolParameter,
    ParameterValueError,
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


@pytest.mark.parametrize(
    "accepts,supplied",
    [
        ("list", "paired"),
        ("paired", "list"),
        ("list", "list:list"),
        ("list,list:paired", "paired"),
        ("sample_sheet", "list"),
        ("paired_or_unpaired", "list"),
    ],
)
def test_from_json_rejects_incompatible_hdca(accepts, supplied):
    with pytest.raises(ParameterValueError, match=f"collection of type '{supplied}' was supplied"):
        _param(accepts).from_json(_hdca(supplied), _trans())


def test_from_json_rejects_incompatible_adapter():
    # Mapping a flat list over a paired_or_unpaired input binds adapters, which
    # declare paired_or_unpaired and so do not fit a list input.
    adapter = PromoteCollectionElementToCollectionAdapter(_collection("list").elements[0])
    with pytest.raises(ParameterValueError, match="collection of type 'paired_or_unpaired' was supplied"):
        _param("list").from_json(adapter, _trans())


@pytest.mark.parametrize(
    "accepts,supplied",
    [
        ("paired", "list:paired"),
        ("list", "list:list"),
        ("paired_or_unpaired", "list"),
    ],
)
def test_from_json_allow_map_over_accepts_mappable_hdca(accepts, supplied):
    hdca = _hdca(supplied)
    assert _param(accepts).from_json(hdca, _trans(), allow_map_over=True) is hdca
    with pytest.raises(ParameterValueError, match=f"collection of type '{supplied}' was supplied"):
        _param(accepts).from_json(hdca, _trans())


@pytest.mark.parametrize(
    "accepts,supplied",
    [
        ("paired", "list"),
        ("list:paired", "list"),
        ("sample_sheet", "list:list"),
    ],
)
def test_from_json_allow_map_over_rejects_unmappable_hdca(accepts, supplied):
    with pytest.raises(ParameterValueError, match=f"collection of type '{supplied}' was supplied"):
        _param(accepts).from_json(_hdca(supplied), _trans(), allow_map_over=True)


def test_from_json_checks_subcollection_element_type():
    paired_element = _collection("list:paired").elements[0]
    assert _param("paired").from_json(paired_element, _trans()) is paired_element
    with pytest.raises(ParameterValueError, match="collection of type 'paired' was supplied"):
        _param("list").from_json(paired_element, _trans())
