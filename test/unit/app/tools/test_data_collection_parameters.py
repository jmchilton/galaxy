"""Collection-type handling in ``DataCollectionToolParameter.from_json``."""

from types import SimpleNamespace

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


def _trans():
    return SimpleNamespace(
        sa_session=None, security=None, workflow_building_mode=workflow_building_modes.DISABLED, history=None
    )


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
        ("list", "list:list"),
        ("paired", "list:paired"),
    ],
)
def test_from_json_accepts_compatible_subcollection_dce(accepts, supplied):
    # Mapping over a nested collection binds each sub-collection element.
    dce = _collection(supplied).elements[0]
    assert _param(accepts).from_json(dce, _trans()) is dce


def test_from_json_accepts_promoted_element_adapter():
    # Mapping a flat list over a paired_or_unpaired input binds adapters.
    adapter = PromoteCollectionElementToCollectionAdapter(_collection("list").elements[0])
    assert _param("paired_or_unpaired").from_json(adapter, _trans()) is adapter


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


def test_from_json_rejects_incompatible_subcollection_dce():
    # e.g. a map-over that splits a list:list into lists for a paired input.
    dce = _collection("list:list").elements[0]
    with pytest.raises(ParameterValueError, match="accepts only 'paired'"):
        _param("paired").from_json(dce, _trans())


def test_from_json_rejects_incompatible_adapter():
    adapter = PromoteCollectionElementToCollectionAdapter(_collection("list").elements[0])
    with pytest.raises(ParameterValueError, match="collection of type 'paired_or_unpaired' was supplied"):
        _param("list").from_json(adapter, _trans())


def _trans_resolving(hdca):
    # ``history_item_dict_to_python`` resolves ``{"src": "hdca", "id": ...}`` through the app.
    app = SimpleNamespace(model=SimpleNamespace(context=SimpleNamespace(get=lambda cls, id: hdca)))
    trans = _trans()
    trans.app = app
    trans.sa_session = app.model.context
    trans.security = SimpleNamespace(decode_id=lambda id: id)
    app.security = trans.security
    return trans


def test_from_json_skips_unexpanded_batch_value():
    # Tool form state for a map-over names the collection being mapped over.
    hdca = _hdca("list:paired")
    value = {"batch": True, "values": [{"src": "hdca", "id": 1, "map_over_type": "paired"}]}
    assert _param("paired").from_json(value, _trans_resolving(hdca)) is hdca


def test_from_json_checks_non_batch_values_dict():
    hdca = _hdca("list:paired")
    value = {"batch": False, "values": [{"src": "hdca", "id": 1}]}
    with pytest.raises(ParameterValueError, match="collection of type 'list:paired' was supplied"):
        _param("paired").from_json(value, _trans_resolving(hdca))


def test_from_json_allow_map_over_accepts_mappable_collection():
    # Workflow runtime values are mapped over the input when they do not match directly.
    hdca = _hdca("list:paired")
    assert _param("paired").from_json(hdca, _trans(), allow_map_over=True) is hdca


def test_from_json_allow_map_over_rejects_unmappable_collection():
    with pytest.raises(ParameterValueError, match="collection of type 'list' was supplied"):
        _param("paired").from_json(_hdca("list"), _trans(), allow_map_over=True)
