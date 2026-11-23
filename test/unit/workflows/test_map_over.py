from typing import cast

from galaxy.managers.context import ProvidesHistoryContext
from galaxy.model.dataset_collections import (
    registry,
    structure,
    type_description,
)
from galaxy.util.bunch import Bunch
from galaxy.workflow.map_over import MapOverPlanner
from galaxy.workflow.modules import InputDescription
from galaxy.workflow.run import WorkflowProgress

TYPE_DESCRIPTION_FACTORY = type_description.CollectionTypeDescriptionFactory(registry.DatasetCollectionTypesRegistry())


def _planner() -> MapOverPlanner:
    return MapOverPlanner(cast(ProvidesHistoryContext, Bunch()))


def _progress_mapped_over_empty(collection_type: str) -> WorkflowProgress:
    empty_structure = structure.Tree([], TYPE_DESCRIPTION_FACTORY.for_collection_type(collection_type))
    return cast(WorkflowProgress, Bunch(subworkflow_structure=empty_structure))


def test_empty_subworkflow_map_over_reserves_outer_structure():
    progress = _progress_mapped_over_empty("list:list")
    assert _planner()._reserve_outer_structure(progress) == ["list"]


def test_empty_subworkflow_map_over_declares_outer_collection_type():
    progress = _progress_mapped_over_empty("list:list")
    input_dict = InputDescription(
        name="input1", label="input1", input_type="dataset_collection", multiple=False, collection_type="paired"
    )
    assert _planner()._declared_collection_input_types(progress, input_dict) == ["list:list"]
