"""Dynamic output collection without constructing Galaxy ORM objects."""

import logging
from uuid import uuid4

from galaxy.job_execution.output_collect_utils import (
    dataset_collector,
    discover_files,
    MaxDiscoveredFilesExceededError,
)
from galaxy.objectstore import persist_extra_files
from galaxy.tool_util.parser.output_objects import ToolOutputCollection

log = logging.getLogger(__name__)

JOB_IO_NAME_MAX_LENGTH = 255


class LightweightJobOutputNameTooLongError(ValueError):
    pass


class LightweightJobContext:
    def __init__(
        self,
        metadata_params,
        tool_provided_metadata,
        object_store,
        export_store,
        working_directory,
        datatypes_registry,
        final_job_state,
        max_discovered_files,
    ):
        self.metadata_params = metadata_params
        self.tool_provided_metadata = tool_provided_metadata
        self.object_store = object_store
        self.export_store = export_store
        self.job_working_directory = str(working_directory)
        self.datatypes_registry = datatypes_registry
        self.final_job_state = final_job_state
        self.max_discovered_files = float("inf") if max_discovered_files is None else max_discovered_files
        self.discovered_file_count = 0

    @property
    def change_datatype_actions(self):
        return self.metadata_params.get("change_datatype_actions", {})

    def increment_discovered_file_count(self):
        self.discovered_file_count += 1
        if self.discovered_file_count > self.max_discovered_files:
            raise MaxDiscoveredFilesExceededError(
                f"Job generated more than maximum number ({self.max_discovered_files}) of output datasets"
            )

    def output_collection_def(self, name):
        output_definition = self.metadata_params["tool"]["output_collections"].get(name)
        return ToolOutputCollection.from_dict(name, output_definition) if output_definition else None

    def create_dataset(self, output_name, match, state):
        dataset = self.export_store.datasets.create(
            self.datatypes_registry,
            self.object_store,
            extension=(self.change_datatype_actions.get(output_name) or match.ext).lower(),
            designation=match.designation,
            visible=match.visible,
            dbkey="?" if match.dbkey == "__input__" else match.dbkey,
            name=match.name or match.designation,
            state=state,
            sources=match.sources,
            hashes=match.hashes,
            created_from_basename=match.created_from_basename,
            tags=match.tag_list,
        )
        return dataset

    def store_dataset(self, dataset, discovered_file, output_name):
        match = discovered_file.match
        path = discovered_file.path
        if path is not None and dataset.state != "deferred":
            if match.link_data:
                dataset.link_to(path)
            else:
                object_store_id = self._object_store_id(output_name)
                if object_store_id:
                    dataset.dataset.object_store_id = object_store_id
                self.object_store.update_from_file(dataset.dataset, file_name=path, create=True)
            if match.extra_files:
                persist_extra_files(self.object_store, match.extra_files, dataset)
                dataset.set_size()
            else:
                dataset.set_size(no_extra_files=True)
        try:
            dataset.set_meta()
        except Exception:
            if dataset.state == "ok":
                dataset.state = "failed_metadata"
            log.exception("Exception occurred while setting metadata")
        try:
            dataset.set_peek()
        except Exception:
            log.exception("Exception occurred while setting dataset peek")
        dataset.set_total_size()

    def add_output_dataset_association(self, output_name, element_identifiers, dataset):
        element_identifier = ":".join(element_identifiers)
        association_name = f"__new_primary_file_{output_name}|{element_identifier}__"
        if len(association_name) > JOB_IO_NAME_MAX_LENGTH:
            raise LightweightJobOutputNameTooLongError(
                f"Tool produced an output name that exceeds the {JOB_IO_NAME_MAX_LENGTH} character name length limit"
            )
        self.export_store.add_job_output_dataset_associations(
            self.metadata_params["job_id_tag"], association_name, dataset
        )

    def _object_store_id(self, output_name):
        job = self.export_store.job
        if job is None:
            return None
        default = getattr(job, "object_store_id", None)
        return (getattr(job, "object_store_id_overrides", None) or {}).get(output_name, default)


class CollectionElementBuilder:
    def __init__(self, collection_type):
        self.collection_type = collection_type
        self.children = {}
        self.rows = {}

    def add(self, identifiers, dataset, row=None):
        identifier = identifiers[0]
        if len(identifiers) == 1:
            self.children[identifier] = dataset
            self.rows[identifier] = row
            return
        child_type = self.collection_type.split(":", 1)[1]
        child = self.children.get(identifier)
        if child is None:
            child = CollectionElementBuilder(child_type)
            self.children[identifier] = child
            self.rows[identifier] = row
        if not isinstance(child, CollectionElementBuilder):
            raise ValueError(f"Collection element [{identifier}] is both a dataset and a nested collection")
        child.add(identifiers[1:], dataset)

    def serialize_elements(self):
        identifiers = list(self.children)
        rank_type = self.collection_type.split(":", 1)[0]
        if rank_type == "paired":
            identifiers = [identifier for identifier in ("forward", "reverse") if identifier in self.children]
        elif rank_type == "paired_or_unpaired":
            paired = [identifier for identifier in ("forward", "reverse") if identifier in self.children]
            identifiers = paired or [identifier for identifier in ("unpaired",) if identifier in self.children]
        elements = []
        for index, identifier in enumerate(identifiers):
            child = self.children[identifier]
            element = {
                "encoded_id": uuid4().hex,
                "model_class": "DatasetCollectionElement",
                "element_type": "dataset_collection" if isinstance(child, CollectionElementBuilder) else "hda",
                "element_index": index,
                "element_identifier": identifier,
                "columns": self.rows.get(identifier),
            }
            if isinstance(child, CollectionElementBuilder):
                element["child_collection"] = child.serialize_collection()
            else:
                element["hda"] = {
                    "encoded_id": child._attributes["encoded_id"],
                    "model_class": "HistoryDatasetAssociation",
                }
            elements.append(element)
        return elements

    def serialize_collection(self):
        elements = self.serialize_elements()
        return {
            "encoded_id": uuid4().hex,
            "model_class": "DatasetCollection",
            "type": self.collection_type,
            "populated_state": "ok",
            "populated_state_message": None,
            "column_definitions": None,
            "element_count": len(elements),
            "elements": elements,
        }


def discovered_collection_extensions(metadata_params, tool_provided_metadata, collection_store, working_directory):
    for name, output_collection in metadata_params.get("output_collections", {}).items():
        collection = collection_store.find(output_collection["id"])
        if collection is None:
            continue
        output_definition_dict = metadata_params["tool"]["output_collections"].get(name)
        if output_definition_dict is None:
            continue
        output_definition = ToolOutputCollection.from_dict(name, output_definition_dict)
        if not output_definition.dynamic_structure:
            continue
        collectors = [
            dataset_collector(description) for description in output_definition.dataset_collector_descriptions
        ]
        for discovered_file in discover_files(
            name,
            tool_provided_metadata,
            collectors,
            str(working_directory),
            collection.collection,
        ):
            yield discovered_file.match.ext.lower()


def collect_dynamic_outputs(context: LightweightJobContext, output_collections):
    for name, hdca in output_collections.items():
        output_definition = context.output_collection_def(name)
        if not output_definition or not output_definition.dynamic_structure:
            continue
        collection = hdca.collection
        collection.populated_state = collection.populated_states.NEW
        collection.replace_elements([])
        try:
            collectors = [
                dataset_collector(description) for description in output_definition.dataset_collector_descriptions
            ]
            discovered_files = list(
                discover_files(
                    name, context.tool_provided_metadata, collectors, context.job_working_directory, collection
                )
            )
            for _ in discovered_files:
                context.increment_discovered_file_count()
            builder = CollectionElementBuilder(collection.collection_type)
            final_job_state = context.final_job_state
            for discovered_file in discovered_files:
                match = discovered_file.match
                effective_state = match.effective_state
                if final_job_state == "ok" and effective_state != "ok":
                    final_job_state = effective_state
                dataset = context.create_dataset(name, match, final_job_state)
                context.store_dataset(dataset, discovered_file, name)
                builder.add(match.element_identifiers, dataset, row=match.row)
                context.add_output_dataset_association(name, match.element_identifiers, dataset)
            collection.replace_elements(builder.serialize_elements())
            collection.mark_as_populated()
        except MaxDiscoveredFilesExceededError:
            collection.handle_population_failed("Job generated more than the maximum number of output datasets.")
            raise
        except LightweightJobOutputNameTooLongError:
            collection.handle_population_failed("Tool produced an output dataset name that is too long.")
            raise
        except Exception:
            log.exception("Problem gathering output collection")
            collection.handle_population_failed("Problem building datasets for collection.")
