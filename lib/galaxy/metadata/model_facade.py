"""Lightweight dataset objects for portable metadata calculation."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

from galaxy.datatypes.metadata import MetadataCollection
from galaxy.schema.states import DatasetState
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
        object.__setattr__(self, "_metadata", attributes.get("metadata") or {})
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
        jobs_path = self.import_directory / "jobs_attrs.txt"
        with jobs_path.open() as handle:
            self._job_attributes = json.load(handle)
        self.job = MetadataJob(self._job_attributes[0]) if self._job_attributes else None

    def add_dataset(self, dataset, include_files=True):
        # Fixed outputs already occur in the input store. Mutations are made
        # directly against their canonical serialized dictionaries.
        return None

    def push_metadata_files(self):
        # File-backed metadata is conservatively routed to the ORM path.
        return None

    def _finalize(self):
        shutil.copytree(self.import_directory, self.export_directory, dirs_exist_ok=True)
        (self.export_directory / "datasets_attrs.txt").write_text(json.dumps(self.datasets._attributes, sort_keys=True))
        (self.export_directory / "jobs_attrs.txt").write_text(json.dumps(self._job_attributes, sort_keys=True))
