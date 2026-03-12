from collections import defaultdict
from typing import (
    TYPE_CHECKING,
)

from pydantic import ValidationError
from typing_extensions import Self

from galaxy.model import CollectionStateSummary
from galaxy.tool_util_models.parameters import (
    AdaptedDataCollectionMergeDatasetsRequestInternal,
    AdaptedDataCollectionMergeListsFlattenedRequestInternal,
    AdaptedDataCollectionMergeListsNestedRequestInternal,
    AdaptedDataCollectionMergeNestedDatasetsRequestInternal,
    AdaptedDataCollectionPromoteCollectionElementToCollectionRequestInternal,
    AdaptedDataCollectionPromoteDatasetsToCollectionRequestInternal,
    AdaptedDataCollectionPromoteDatasetToCollectionRequestInternal,
    AdaptedDataCollectionRequestInternalTypeAdapter,
    AdaptedDataCollectionRequestTypeAdapter,
    AdapterElementRequestInternal,
    DataRequestInternalHda,
    DataRequestInternalHdca,
    DatasetCollectionElementReference,
)

if TYPE_CHECKING:
    from galaxy.model import (
        DatasetCollectionElement,
        HistoryDatasetAssociation,
        HistoryDatasetCollectionAssociation,
    )


class CollectionAdapter:
    # wrap model objects with extra context to create psuedo or ephemeral
    # collections for tool processing code. Used across tool actions and
    # tool evaluation.

    @property
    def dataset_action_tuples(self):
        raise NotImplementedError()

    @property
    def dataset_states_and_extensions_summary(self):
        raise NotImplementedError()

    @property
    def dataset_instances(self):
        raise NotImplementedError()

    @property
    def elements(self):
        raise NotImplementedError()

    def to_adapter_model(self):
        # json kwds to recover state from database after the job has been
        # recorded
        raise NotImplementedError()

    @property
    def adapting(self):
        # return the the thing we're adapting for recording an actual link
        # in the database
        raise NotImplementedError()

    @property
    def collection(self) -> Self:
        # this object serves an adapter to the collection instance and to the collection,
        # may want to break this out someday. For now though just return self when asking for
        # the collection object.
        return self

    @property
    def allow_implicit_mapping(self) -> bool:
        return True

    @property
    def populated(self) -> bool:
        return True

    @property
    def column_definitions(self):
        return None

    def __getitem__(self, index):
        return self.elements[index]

    @property
    def collection_type(self) -> str:
        raise NotImplementedError()


class DCECollectionAdapter(CollectionAdapter):
    # adapt a DatasetCollectionElement to act as collection.
    _dce: "DatasetCollectionElement"

    def __init__(self, dataset_collection_element: "DatasetCollectionElement"):
        self._dce = dataset_collection_element

    @property
    def dataset_action_tuples(self):
        if self._dce.child_collection:
            return self._dce.child_collection.dataset_action_tuples
        else:
            hda = self._dce.dataset_instance
            return [(permission.action, permission.role_id) for permission in hda.dataset.actions]

    @property
    def dataset_states_and_extensions_summary(self):
        if self._dce.child_collection:
            return self._dce.child_collection.dataset_states_and_extensions_summary
        else:
            hda = self._dce.dataset_instance
            dbkeys = [hda.dbkey] if hda.dbkey else []
            extensions = [hda.extension] if hda.extension else []
            states = {hda.dataset.state: 1} if hda.dataset.state else {}
            deleted = 1 if hda.deleted or (hda.dataset and hda.dataset.deleted) else 0
            return CollectionStateSummary(dbkeys=dbkeys, extensions=extensions, states=states, deleted=deleted)

    @property
    def dataset_instances(self):
        return self._dce.dataset_instances

    @property
    def elements(self):
        if self._dce.child_collection:
            return self._dce.child_collection.elements
        else:
            return [self._dce]

    @property
    def adapting(self):
        return self._dce

    @property
    def _adapting_src_dict(self):
        return {
            "src": "dce",
            "id": self._dce.id,
        }


class PromoteCollectionElementToCollectionAdapter(DCECollectionAdapter):
    # allow a singleton list element to act as paired_or_unpaired collection

    def to_adapter_model(self) -> AdaptedDataCollectionPromoteCollectionElementToCollectionRequestInternal:
        adapting_model = DatasetCollectionElementReference.model_validate(self._adapting_src_dict)
        return AdaptedDataCollectionPromoteCollectionElementToCollectionRequestInternal(
            src="CollectionAdapter",
            adapter_type="PromoteCollectionElementToCollection",
            adapting=adapting_model,
        )

    @property
    def collection_type(self) -> str:
        return "paired_or_unpaired"


class PromoteDatasetToCollection(CollectionAdapter):

    def __init__(self, hda: "HistoryDatasetAssociation", collection_type: str):
        assert collection_type in ["list", "paired_or_unpaired"]
        self._hda = hda
        self._collection_type = collection_type

    def to_adapter_model(self) -> AdaptedDataCollectionPromoteDatasetToCollectionRequestInternal:
        adapting = {
            "src": "hda",
            "id": self._hda.id,
        }
        adapting_model = DataRequestInternalHda.model_validate(adapting)
        return AdaptedDataCollectionPromoteDatasetToCollectionRequestInternal(
            src="CollectionAdapter",
            adapter_type="PromoteDatasetToCollection",
            collection_type=self._collection_type,
            adapting=adapting_model,
        )

    @property
    def dataset_action_tuples(self):
        hda = self._hda
        return [(permission.action, permission.role_id) for permission in hda.dataset.actions]

    @property
    def dataset_states_and_extensions_summary(self):
        hda = self._hda
        dbkeys = [hda.dbkey] if hda.dbkey else []
        extensions = [hda.extension] if hda.extension else []
        states = {hda.dataset.state: 1} if hda.dataset.state else {}
        deleted = 1 if hda.deleted or (hda.dataset and hda.dataset.deleted) else 0
        return CollectionStateSummary(dbkeys=dbkeys, extensions=extensions, states=states, deleted=deleted)

    @property
    def dataset_instances(self):
        return [self._hda]

    @property
    def elements(self):
        identifier = self._hda.name
        if self._collection_type == "paired_or_unpaired":
            identifier = "unpaired"
        return [TransientCollectionAdapterDatasetInstanceElement(identifier, self._hda)]

    @property
    def adapting(self):
        return self._hda

    @property
    def collection_type(self) -> str:
        return self._collection_type


class PromoteDatasetsToCollection(CollectionAdapter):
    _collection_type: str
    _elements: list["TransientCollectionAdapterDatasetInstanceElement"]

    def __init__(self, elements: list["TransientCollectionAdapterDatasetInstanceElement"], collection_type: str):
        assert collection_type in ["paired", "paired_or_unpaired"]
        self._collection_type = collection_type
        self._elements = elements

    def to_adapter_model(self) -> AdaptedDataCollectionPromoteDatasetsToCollectionRequestInternal:
        element_models = []
        for element in self._elements:
            element_model = AdapterElementRequestInternal(
                src="hda",
                id=element.hda.id,
                name=element.element_identifier,
            )
            element_models.append(element_model)
        return AdaptedDataCollectionPromoteDatasetsToCollectionRequestInternal(
            src="CollectionAdapter",
            adapter_type="PromoteDatasetsToCollection",
            collection_type=self._collection_type,
            adapting=element_models,
        )

    @property
    def dataset_instances(self):
        return [e.dataset_instance for e in self._elements]

    @property
    def elements(self):
        return self._elements

    @property
    def element_object(self) -> Self:
        # this is a stand-in or adapter for a real collection so this might be the object?
        return self

    @property
    def dataset_action_tuples(self):
        tuples = []
        for hda in self.dataset_instances:
            tuples.append([(permission.action, permission.role_id) for permission in hda.dataset.actions])
        return tuples

    @property
    def dataset_states_and_extensions_summary(self):
        dbkeys = set()
        extensions = set()
        states: dict[str, int] = defaultdict(int)
        deleted = 0
        for hda in self.dataset_instances:
            if hda.dbkey:
                dbkeys.add(hda.dbkey)
            if hda.extension:
                extensions.add(hda.extension)
            if hda.dataset.state:
                states[hda.dataset.state] += 1
            if hda.deleted or (hda.dataset and hda.dataset.deleted):
                deleted += 1
        return CollectionStateSummary(
            dbkeys=sorted(dbkeys), extensions=sorted(extensions), states=states, deleted=deleted
        )

    @property
    def adapting(self):
        return self._elements

    @property
    def collection_type(self) -> str:
        return self._collection_type


class TransientCollectionAdapterDatasetInstanceElement:
    def __init__(self, element_identifier, hda: "HistoryDatasetAssociation"):
        self.element_identifier = element_identifier
        self.child_collection = None
        self.hda = hda

    @property
    def element_object(self):
        return self.hda

    @property
    def dataset_instance(self):
        return self.hda

    @property
    def is_collection(self):
        return False

    @property
    def columns(self):
        return None


class TransientCollectionAdapterCollectionElement:
    """Wraps an HDCA as a collection element for nested merge adapters."""

    def __init__(self, element_identifier: str, hdca: "HistoryDatasetCollectionAssociation"):
        self.element_identifier = element_identifier
        self._hdca = hdca

    @property
    def child_collection(self):
        return self._hdca.collection

    @property
    def element_object(self):
        return self._hdca.collection

    @property
    def dataset_instance(self):
        return None

    @property
    def is_collection(self):
        return True

    @property
    def columns(self):
        return None


class MergeDatasetsAdapter(CollectionAdapter):
    """Merge multiple datasets into a list collection (Path A)."""

    def __init__(self, datasets: list["HistoryDatasetAssociation"]):
        self._datasets = datasets
        self._elements = [
            TransientCollectionAdapterDatasetInstanceElement(str(i), hda)
            for i, hda in enumerate(datasets)
        ]

    @property
    def collection_type(self) -> str:
        return "list"

    @property
    def elements(self):
        return self._elements

    @property
    def dataset_instances(self):
        return list(self._datasets)

    @property
    def dataset_action_tuples(self):
        tuples = []
        for hda in self._datasets:
            tuples.extend([(p.action, p.role_id) for p in hda.dataset.actions])
        return tuples

    @property
    def dataset_states_and_extensions_summary(self):
        dbkeys = set()
        extensions = set()
        states: dict[str, int] = defaultdict(int)
        deleted = 0
        for hda in self._datasets:
            if hda.dbkey:
                dbkeys.add(hda.dbkey)
            if hda.extension:
                extensions.add(hda.extension)
            if hda.dataset.state:
                states[hda.dataset.state] += 1
            if hda.deleted or (hda.dataset and hda.dataset.deleted):
                deleted += 1
        return CollectionStateSummary(dbkeys=sorted(dbkeys), extensions=sorted(extensions), states=states, deleted=deleted)

    @property
    def adapting(self):
        return self._elements

    def to_adapter_model(self) -> AdaptedDataCollectionMergeDatasetsRequestInternal:
        return AdaptedDataCollectionMergeDatasetsRequestInternal(
            src="CollectionAdapter",
            adapter_type="MergeDatasets",
            adapting=[DataRequestInternalHda(src="hda", id=hda.id) for hda in self._datasets],
        )


class MergeListsFlattenedAdapter(CollectionAdapter):
    """Flatten multiple list collections into one list (Path B)."""

    def __init__(self, hdcas: list["HistoryDatasetCollectionAssociation"]):
        self._hdcas = hdcas

    @property
    def collection_type(self) -> str:
        return "list"

    @property
    def elements(self):
        result = []
        idx = 0
        for hdca in self._hdcas:
            for elem in hdca.collection.elements:
                result.append(TransientCollectionAdapterDatasetInstanceElement(
                    str(idx), elem.dataset_instance
                ))
                idx += 1
        return result

    @property
    def dataset_instances(self):
        instances = []
        for hdca in self._hdcas:
            instances.extend(hdca.dataset_instances)
        return instances

    @property
    def dataset_action_tuples(self):
        tuples = []
        for hdca in self._hdcas:
            tuples.extend(hdca.collection.dataset_action_tuples)
        return tuples

    @property
    def dataset_states_and_extensions_summary(self):
        dbkeys = set()
        extensions = set()
        states: dict[str, int] = defaultdict(int)
        deleted = 0
        for hdca in self._hdcas:
            summary = hdca.collection.dataset_states_and_extensions_summary
            dbkeys.update(summary.dbkeys)
            extensions.update(summary.extensions)
            for state, count in summary.states.items():
                states[state] += count
            deleted += summary.deleted
        return CollectionStateSummary(dbkeys=sorted(dbkeys), extensions=sorted(extensions), states=states, deleted=deleted)

    @property
    def adapting(self):
        return self._hdcas

    def to_adapter_model(self) -> AdaptedDataCollectionMergeListsFlattenedRequestInternal:
        return AdaptedDataCollectionMergeListsFlattenedRequestInternal(
            src="CollectionAdapter",
            adapter_type="MergeListsFlattened",
            adapting=[DataRequestInternalHdca(src="hdca", id=hdca.id) for hdca in self._hdcas],
        )


class MergeListsNestedAdapter(CollectionAdapter):
    """Nest multiple list collections as sub-collections (Path C)."""

    def __init__(self, hdcas: list["HistoryDatasetCollectionAssociation"], input_collection_type: str):
        self._hdcas = hdcas
        self._input_collection_type = input_collection_type

    @property
    def collection_type(self) -> str:
        return f"list:{self._input_collection_type}"

    @property
    def elements(self):
        return [TransientCollectionAdapterCollectionElement(str(i), hdca)
                for i, hdca in enumerate(self._hdcas)]

    @property
    def dataset_instances(self):
        instances = []
        for hdca in self._hdcas:
            instances.extend(hdca.dataset_instances)
        return instances

    @property
    def dataset_action_tuples(self):
        tuples = []
        for hdca in self._hdcas:
            tuples.extend(hdca.collection.dataset_action_tuples)
        return tuples

    @property
    def dataset_states_and_extensions_summary(self):
        dbkeys = set()
        extensions = set()
        states: dict[str, int] = defaultdict(int)
        deleted = 0
        for hdca in self._hdcas:
            summary = hdca.collection.dataset_states_and_extensions_summary
            dbkeys.update(summary.dbkeys)
            extensions.update(summary.extensions)
            for state, count in summary.states.items():
                states[state] += count
            deleted += summary.deleted
        return CollectionStateSummary(dbkeys=sorted(dbkeys), extensions=sorted(extensions), states=states, deleted=deleted)

    @property
    def adapting(self):
        return self._hdcas

    def to_adapter_model(self) -> AdaptedDataCollectionMergeListsNestedRequestInternal:
        return AdaptedDataCollectionMergeListsNestedRequestInternal(
            src="CollectionAdapter",
            adapter_type="MergeListsNested",
            input_collection_type=self._input_collection_type,
            adapting=[DataRequestInternalHdca(src="hdca", id=hdca.id) for hdca in self._hdcas],
        )


class TransientCollectionAdapterSubListElement:
    """Virtual sub-list element wrapping a single dataset as a 1-element list.

    Used by MergeNestedDatasetsAdapter to build list:list from individual HDAs.
    CWL merge_nested: [A, B] -> [[A], [B]]
    """

    def __init__(self, element_identifier: str, elements: list[TransientCollectionAdapterDatasetInstanceElement]):
        self.element_identifier = element_identifier
        self._elements = elements

    @property
    def child_collection(self):
        return self

    @property
    def element_object(self):
        return self

    @property
    def is_collection(self):
        return True

    @property
    def elements(self):
        return self._elements

    @property
    def collection_type(self):
        return "list"

    @property
    def dataset_instances(self):
        return [e.dataset_instance for e in self._elements]


class MergeNestedDatasetsAdapter(CollectionAdapter):
    """Wrap multiple individual datasets into list:list (Path D).

    CWL merge_nested for File inputs: [A, B] -> [[A], [B]]
    Each HDA becomes a 1-element sub-list.
    """

    def __init__(self, datasets: list["HistoryDatasetAssociation"]):
        self._datasets = datasets

    @property
    def collection_type(self) -> str:
        return "list:list"

    @property
    def elements(self):
        result = []
        for i, hda in enumerate(self._datasets):
            inner_element = TransientCollectionAdapterDatasetInstanceElement("0", hda)
            result.append(TransientCollectionAdapterSubListElement(str(i), [inner_element]))
        return result

    @property
    def dataset_instances(self):
        return list(self._datasets)

    @property
    def dataset_action_tuples(self):
        tuples = []
        for hda in self._datasets:
            tuples.extend([(p.action, p.role_id) for p in hda.dataset.actions])
        return tuples

    @property
    def dataset_states_and_extensions_summary(self):
        dbkeys = set()
        extensions = set()
        states: dict[str, int] = defaultdict(int)
        deleted = 0
        for hda in self._datasets:
            if hda.dbkey:
                dbkeys.add(hda.dbkey)
            if hda.extension:
                extensions.add(hda.extension)
            if hda.dataset.state:
                states[hda.dataset.state] += 1
            if hda.deleted or (hda.dataset and hda.dataset.deleted):
                deleted += 1
        return CollectionStateSummary(dbkeys=sorted(dbkeys), extensions=sorted(extensions), states=states, deleted=deleted)

    @property
    def adapting(self):
        return self._datasets

    def to_adapter_model(self) -> "AdaptedDataCollectionMergeNestedDatasetsRequestInternal":
        return AdaptedDataCollectionMergeNestedDatasetsRequestInternal(
            src="CollectionAdapter",
            adapter_type="MergeNestedDatasets",
            adapting=[DataRequestInternalHda(src="hda", id=hda.id) for hda in self._datasets],
        )


def recover_adapter(wrapped_object, adapter_model):
    adapter_type = adapter_model.adapter_type
    if adapter_type == "PromoteCollectionElementToCollection":
        return PromoteCollectionElementToCollectionAdapter(wrapped_object)
    elif adapter_type == "PromoteDatasetToCollection":
        return PromoteDatasetToCollection(wrapped_object, adapter_model.collection_type)
    elif adapter_type == "PromoteDatasetsToCollection":
        return PromoteDatasetsToCollection(wrapped_object, adapter_model.collection_type)
    elif adapter_type == "MergeDatasets":
        return MergeDatasetsAdapter(wrapped_object)
    elif adapter_type == "MergeListsFlattened":
        return MergeListsFlattenedAdapter(wrapped_object)
    elif adapter_type == "MergeListsNested":
        return MergeListsNestedAdapter(wrapped_object, adapter_model.input_collection_type)
    elif adapter_type == "MergeNestedDatasets":
        return MergeNestedDatasetsAdapter(wrapped_object)
    else:
        raise Exception(f"Unknown collection adapter encountered {adapter_type}")


def validate_collection_adapter_src_dict(value):
    try:
        return AdaptedDataCollectionRequestInternalTypeAdapter.validate_python(value)
    except ValidationError:
        return AdaptedDataCollectionRequestTypeAdapter.validate_python(value)
