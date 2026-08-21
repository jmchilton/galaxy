"""Lightweight dataset objects for portable metadata calculation."""

import json
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from galaxy.datatypes.metadata import MetadataCollection
from galaxy.schema.states import (
    DatasetCollectionPopulatedState,
    DatasetState,
)
from galaxy.util import nice_size as format_size


class MetadataDataset:
    """Dataset-shaped view over the nested model-store dataset attributes."""

    states = DatasetState
    non_ready_states = (
        states.NEW,
        states.UPLOAD,
        states.QUEUED,
        states.RUNNING,
        states.SETTING_METADATA,
    )

    def __init__(self, attributes: dict[str, Any], object_store=None):
        object.__setattr__(self, "_attributes", attributes)
        object.__setattr__(self, "object_store", object_store)
        attributes.setdefault("deleted", False)
        attributes.setdefault("purged", False)
        attributes.setdefault("purgable", True)
        attributes.setdefault("sources", [])
        attributes.setdefault("hashes", [])

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        class_attribute = getattr(type(self), name, None)
        if isinstance(class_attribute, property) and class_attribute.fset is not None:
            class_attribute.fset(self, value)
        elif name in {"_attributes", "object_store", "external_extra_files_path"}:
            object.__setattr__(self, name, value)
        else:
            self._attributes[name] = value

    def get_file_name(self, sync_cache: bool = True, auth=None) -> str:
        if self.external_filename:
            return os.path.abspath(self.external_filename)
        if self.object_store is None:
            return ""
        if self.object_store.exists(self):
            return self.object_store.get_filename(self, sync_cache=sync_cache, auth=auth)
        return ""

    @property
    def _extra_files_rel_path(self):
        return self._extra_files_path

    @property
    def extra_files_path(self):
        external_path = getattr(self, "external_extra_files_path", None)
        if external_path:
            return os.path.abspath(external_path)
        if self.object_store is None or self._extra_files_rel_path is None:
            return None
        return self.object_store.get_filename(self, dir_only=True, extra_dir=self._extra_files_rel_path)

    @extra_files_path.setter
    def extra_files_path(self, value):
        self.external_extra_files_path = value

    def extra_files_path_exists(self):
        path = self.extra_files_path
        return bool(path and os.path.exists(path))

    def _calculate_size(self) -> int:
        filename = self.get_file_name()
        if filename:
            try:
                return os.path.getsize(filename)
            except OSError:
                return 0
        return 0

    def get_size(self, nice_size: bool = False, calculate_size: bool = True):
        size = int(self.file_size or 0)
        if not size and calculate_size:
            size = self._calculate_size()
        return format_size(size) if nice_size else size

    def set_size(self, no_extra_files: bool = False):
        if not self.file_size:
            self.file_size = self._calculate_size()
            if no_extra_files:
                self.total_size = self.file_size

    def set_total_size(self):
        if self.file_size is None:
            self.set_size()
        total_size = self.file_size or 0
        if self.extra_files_path_exists():
            for root, _, files in os.walk(self.extra_files_path):
                total_size += sum(
                    os.path.getsize(os.path.join(root, filename))
                    for filename in files
                    if os.path.exists(os.path.join(root, filename))
                )
        self.total_size = total_size
        return total_size

    def extra_files_path_name_from(self, object_store):
        store_by = object_store.get_store_by(self)
        return f"dataset_{getattr(self, store_by)}_files" if store_by else None


class MetadataDatasetInstance:
    """DatasetInstance-shaped view used by datatype metadata methods."""

    states = DatasetState

    def __init__(self, attributes: dict[str, Any], datatypes_registry, object_store=None):
        object.__setattr__(self, "_attributes", attributes)
        object.__setattr__(self, "_datatypes_registry", datatypes_registry)
        object.__setattr__(self, "dataset", MetadataDataset(attributes["dataset"], object_store=object_store))
        metadata = attributes.get("metadata")
        if metadata is None:
            metadata = {}
            attributes["metadata"] = metadata
        object.__setattr__(self, "_metadata", metadata)
        object.__setattr__(self, "_metadata_collection", MetadataCollection(self))
        object.__setattr__(self, "_state", None)

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        class_attribute = getattr(type(self), name, None)
        if isinstance(class_attribute, property) and class_attribute.fset is not None:
            class_attribute.fset(self, value)
        elif name in {"_attributes", "_datatypes_registry", "dataset", "_metadata", "_metadata_collection", "_state"}:
            object.__setattr__(self, name, value)
        else:
            self._attributes[name] = value

    @property
    def ext(self):
        return self.extension

    @property
    def dbkey(self):
        return self.metadata.dbkey

    @property
    def metadata(self):
        return self._metadata_collection

    @metadata.setter
    def metadata(self, value):
        self._metadata = self.metadata.make_dict_copy(value)

    @property
    def datatype(self):
        return self._datatypes_registry.get_datatype_by_extension(self.extension)

    @property
    def state(self):
        return self._state or self.dataset.state

    @state.setter
    def state(self, value):
        if value in (DatasetState.FAILED_METADATA, DatasetState.SETTING_METADATA):
            self._state = value
        else:
            self._state = None
            self.dataset.state = value
            self._attributes["state"] = value

    @property
    def extra_files_path(self):
        return self.dataset.extra_files_path

    @property
    def creating_job(self):
        return None

    @property
    def created_from_basename(self):
        return self.dataset.created_from_basename

    @created_from_basename.setter
    def created_from_basename(self, value):
        self.dataset.created_from_basename = value

    def get_file_name(self, sync_cache: bool = True, auth=None):
        return self.dataset.get_file_name(sync_cache=sync_cache, auth=auth)

    def get_size(self, nice_size: bool = False, calculate_size: bool = True):
        size = self.dataset.get_size(nice_size=False, calculate_size=calculate_size)
        return format_size(size) if nice_size else size

    def get_total_size(self):
        if self.dataset.total_size is None:
            return self.dataset.set_total_size()
        return self.dataset.total_size

    def set_total_size(self):
        return self.dataset.set_total_size()

    def set_size(self, no_extra_files: bool = False):
        return self.dataset.set_size(no_extra_files=no_extra_files)

    def has_data(self):
        return self.state not in self.dataset.non_ready_states and self.get_size() > 0

    def get_mime(self):
        return self._datatypes_registry.get_mimetype_by_extension(self.extension.lower())

    def set_peek(self, line_count=None, **kwds):
        try:
            return self.datatype.set_peek(self, line_count=line_count, **kwds)
        except TypeError:
            return self.datatype.set_peek(self, **kwds)

    def init_meta(self, copy_from=None):
        return self.datatype.init_meta(self, copy_from=copy_from)

    def set_meta(self, **kwds):
        self.clear_associated_files(metadata_safe=True)
        return self.datatype.set_meta(self, **kwds)

    def change_datatype(self, extension):
        self.extension = extension

    def link_to(self, filename):
        self.dataset.external_filename = filename

    def clear_associated_files(self, metadata_safe: bool = False, purge: bool = False):
        return None

    def get_converted_files_by_type(self, file_type):
        return {}


class MetadataDatasetStore:
    def __init__(self, datasets: dict[Any, MetadataDatasetInstance], attributes: list[dict[str, Any]]):
        self._datasets = datasets
        self._attributes = attributes

    @classmethod
    def from_directory(cls, directory, datatypes_registry, object_store=None):
        datasets_path = Path(directory) / "datasets_attrs.txt"
        with datasets_path.open() as handle:
            attributes = json.load(handle)
        datasets = {}
        for dataset_attributes in attributes:
            if dataset_attributes.get("model_class") != "HistoryDatasetAssociation":
                raise ValueError("Lightweight metadata supports HistoryDatasetAssociation outputs only")
            dataset = MetadataDatasetInstance(dataset_attributes, datatypes_registry, object_store=object_store)
            datasets[dataset.id] = dataset
        return cls(datasets, attributes)

    def find(self, dataset_id):
        return self._datasets.get(dataset_id)

    def create(
        self,
        datatypes_registry,
        object_store=None,
        *,
        extension,
        designation,
        visible,
        dbkey,
        name,
        info=None,
        state="ok",
        sources=None,
        hashes=None,
        created_from_basename=None,
        tags=None,
    ):
        dataset_instance_key = uuid4().hex
        dataset_key = uuid4().hex
        dataset_uuid = str(uuid4())
        dataset_attributes = {
            "encoded_id": dataset_instance_key,
            "model_class": "HistoryDatasetAssociation",
            "name": name or "Unnamed dataset",
            "info": info,
            "blurb": None,
            "peek": None,
            "extension": extension,
            "metadata": {"dbkey": dbkey},
            "metadata_deferred": state == "deferred",
            "designation": designation,
            "deleted": False,
            "visible": visible,
            "dataset_uuid": dataset_uuid,
            "validated_state": "unknown",
            "validated_state_message": None,
            "state": state,
            "hid": None,
            "annotation": "",
            "tags": tags or [],
            "tool_version": None,
            "copied_from_history_dataset_association_id_chain": [],
            "dataset": {
                "encoded_id": dataset_key,
                "model_class": "Dataset",
                "state": state,
                "deleted": False,
                "purged": False,
                "purgable": True,
                "external_filename": None,
                "_extra_files_path": None,
                "file_size": None,
                "object_store_id": None,
                "total_size": None,
                "created_from_basename": created_from_basename,
                "uuid": dataset_uuid,
                "hashes": [
                    {
                        "encoded_id": uuid4().hex,
                        "model_class": "DatasetHash",
                        "hash_function": item["hash_function"],
                        "hash_value": item["hash_value"],
                        "extra_files_path": item.get("extra_files_path"),
                    }
                    for item in (hashes or [])
                ],
                "sources": [
                    {
                        "encoded_id": uuid4().hex,
                        "model_class": "DatasetSource",
                        "source_uri": item["source_uri"],
                        "extra_files_path": item.get("extra_files_path"),
                        "transform": item.get("transform"),
                        "requested_transform": item.get("requested_transform"),
                        "hashes": item.get("hashes", []),
                    }
                    for item in (sources or [])
                ],
            },
        }
        dataset = MetadataDatasetInstance(dataset_attributes, datatypes_registry, object_store=object_store)
        dataset.init_meta()
        self._attributes.append(dataset_attributes)
        self._datasets[dataset_instance_key] = dataset
        return dataset


class MetadataDatasetCollectionElement:
    """Collection-element-shaped view over serialized collection attributes."""

    def __init__(self, attributes: dict[str, Any], datasets: MetadataDatasetStore):
        object.__setattr__(self, "_attributes", attributes)
        object.__setattr__(self, "_datasets", datasets)
        child_attributes = attributes.get("child_collection")
        object.__setattr__(
            self,
            "child_collection",
            MetadataDatasetCollection(child_attributes, datasets) if child_attributes is not None else None,
        )

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name in {"_attributes", "_datasets", "child_collection"}:
            object.__setattr__(self, name, value)
        else:
            self._attributes[name] = value

    @property
    def is_collection(self):
        return self.child_collection is not None

    @property
    def dataset_instance(self):
        if self.is_collection:
            raise AttributeError("Nested collection has no associated dataset_instance")
        hda_reference = self._attributes.get("hda") or {}
        dataset_id = hda_reference.get("id", hda_reference.get("encoded_id"))
        return self._datasets.find(dataset_id)


class MetadataDatasetCollection:
    """DatasetCollection-shaped view over serialized collection attributes."""

    populated_states = DatasetCollectionPopulatedState

    def __init__(self, attributes: dict[str, Any], datasets: MetadataDatasetStore):
        object.__setattr__(self, "_attributes", attributes)
        object.__setattr__(self, "_datasets", datasets)
        object.__setattr__(
            self,
            "elements",
            [MetadataDatasetCollectionElement(element, datasets) for element in attributes.get("elements", [])],
        )

    def __getattr__(self, name):
        if name == "collection_type":
            return self._attributes["type"]
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name in {"_attributes", "_datasets", "elements"}:
            object.__setattr__(self, name, value)
        else:
            self._attributes["type" if name == "collection_type" else name] = value

    @property
    def dataset_instances(self):
        datasets = []
        for element in self.elements:
            if element.is_collection:
                datasets.extend(element.child_collection.dataset_instances)
            elif dataset := element.dataset_instance:
                datasets.append(dataset)
        return datasets

    def mark_as_populated(self):
        self.populated_state = self.populated_states.OK
        self.populated_state_message = None
        self.element_count = len(self.elements)

    def handle_population_failed(self, message):
        self.populated_state = self.populated_states.FAILED
        self.populated_state_message = message

    def replace_elements(self, elements: list[dict[str, Any]]):
        self._attributes["elements"] = elements
        object.__setattr__(
            self,
            "elements",
            [MetadataDatasetCollectionElement(element, self._datasets) for element in elements],
        )
        self.element_count = len(elements)


class MetadataDatasetCollectionInstance:
    """HDCA-shaped view over serialized collection attributes."""

    def __init__(self, attributes: dict[str, Any], datasets: MetadataDatasetStore):
        object.__setattr__(self, "_attributes", attributes)
        object.__setattr__(self, "collection", MetadataDatasetCollection(attributes["collection"], datasets))

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        if name in {"_attributes", "collection"}:
            object.__setattr__(self, name, value)
        else:
            self._attributes[name] = value

    @property
    def dataset_instances(self):
        return self.collection.dataset_instances


class MetadataDatasetCollectionStore:
    def __init__(
        self,
        collections: dict[Any, MetadataDatasetCollectionInstance],
        attributes: list[dict[str, Any]],
        datasets: MetadataDatasetStore,
    ):
        self._collections = collections
        self._attributes = attributes
        self._datasets = datasets

    @classmethod
    def from_directory(cls, directory, datasets: MetadataDatasetStore):
        collections_path = Path(directory) / "collections_attrs.txt"
        with collections_path.open() as handle:
            attributes = json.load(handle)
        collections = {}
        for collection_attributes in attributes:
            if collection_attributes.get("model_class") != "HistoryDatasetCollectionAssociation":
                raise ValueError("Lightweight metadata supports HistoryDatasetCollectionAssociation outputs only")
            collection = MetadataDatasetCollectionInstance(collection_attributes, datasets)
            collections[collection.id] = collection
        return cls(collections, attributes, datasets)

    def find(self, collection_id):
        return self._collections.get(collection_id)

    def create(self, name, collection_type, column_definitions=None):
        collection_instance_key = uuid4().hex
        collection_attributes = {
            "encoded_id": collection_instance_key,
            "model_class": "HistoryDatasetCollectionAssociation",
            "display_name": name,
            "state": "new",
            "hid": None,
            "implicit_output_name": None,
            "copied_from_history_dataset_collection_association_id_chain": [],
            "collection": {
                "encoded_id": uuid4().hex,
                "model_class": "DatasetCollection",
                "type": collection_type,
                "populated_state": "new",
                "populated_state_message": None,
                "column_definitions": column_definitions,
                "element_count": 0,
                "elements": [],
            },
        }
        collection = MetadataDatasetCollectionInstance(collection_attributes, self._datasets)
        self._attributes.append(collection_attributes)
        self._collections[collection_instance_key] = collection
        return collection


class MetadataJob:
    """Job-shaped view over an existing serialized model-store job."""

    def __init__(self, attributes: dict[str, Any]):
        object.__setattr__(self, "_attributes", attributes)

    def __getattr__(self, name):
        try:
            return self._attributes[name]
        except KeyError:
            raise AttributeError(name) from None

    def __setattr__(self, name, value):
        self._attributes[name] = value

    def set_streams(self, tool_stdout, tool_stderr, job_stdout=None, job_stderr=None, job_messages=None):
        self.tool_stdout = tool_stdout
        self.tool_stderr = tool_stderr
        self.job_stdout = job_stdout
        self.job_stderr = job_stderr
        if job_messages is not None:
            self.job_messages = job_messages


class MetadataModelExportStore:
    """Edit an existing metadata model-store without materializing ORM objects."""

    def __init__(self, import_directory, export_directory, datatypes_registry, object_store=None):
        self.import_directory = Path(import_directory)
        self.export_directory = Path(export_directory)
        self.datasets = MetadataDatasetStore.from_directory(
            self.import_directory,
            datatypes_registry,
            object_store=object_store,
        )
        self.dataset_collections = MetadataDatasetCollectionStore.from_directory(
            self.import_directory,
            self.datasets,
        )
        jobs_path = self.import_directory / "jobs_attrs.txt"
        with jobs_path.open() as handle:
            self._job_attributes = json.load(handle)
        self.job = MetadataJob(self._job_attributes[0]) if self._job_attributes else None

    def add_dataset(self, dataset, include_files=True):
        # Fixed outputs already occur in the input store. Mutations are made
        # directly against their canonical serialized dictionaries.
        return None

    def add_job_output_dataset_associations(self, job_id, name, dataset):
        job_attributes = next((job for job in self._job_attributes if job.get("id") == job_id), None)
        if job_attributes is None:
            job_attributes = {"id": job_id, "output_dataset_mapping": {}}
            self._job_attributes.append(job_attributes)
        output_mapping = job_attributes.setdefault("output_dataset_mapping", {})
        output_mapping.setdefault(name, []).append(dataset._attributes.get("id", dataset._attributes["encoded_id"]))

    def push_metadata_files(self):
        # File-backed metadata is conservatively routed to the ORM path.
        return None

    def _finalize(self):
        shutil.copytree(self.import_directory, self.export_directory, dirs_exist_ok=True)
        (self.export_directory / "datasets_attrs.txt").write_text(json.dumps(self.datasets._attributes, sort_keys=True))
        (self.export_directory / "collections_attrs.txt").write_text(
            json.dumps(self.dataset_collections._attributes, sort_keys=True)
        )
        (self.export_directory / "jobs_attrs.txt").write_text(json.dumps(self._job_attributes, sort_keys=True))
