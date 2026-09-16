"""Dynamic output collection without constructing Galaxy ORM objects."""

import logging
from uuid import uuid4

from galaxy.exceptions import RequestParameterInvalidException
from galaxy.job_execution.output_collect_utils import (
    dataset_collector,
    DEFAULT_DATASET_COLLECTOR,
    discover_files,
    discovered_file_for_element,
    MaxDiscoveredFilesExceededError,
    OutputCollectionSecurityError,
    safe_path_from_directory,
    validate_unnamed_outputs,
)
from galaxy.objectstore import persist_extra_files
from galaxy.tool_util.parser.output_objects import (
    ToolOutput,
    ToolOutputCollection,
)

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
        # Match the ORM context's compatibility defaults for jobs prepared by older Galaxy versions.
        self.allows_unnamed_outputs = metadata_params.get("allows_unnamed_outputs", True)
        self.allows_external_output_paths = metadata_params.get("allows_external_output_paths", True)
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

    def output_def(self, name):
        output_definition = self.metadata_params["tool"]["outputs"].get(name)
        return ToolOutput.from_dict(name, output_definition) if output_definition else None

    def create_dataset(self, output_name, match, state, *, info=None, metadata=None, dataset=None):
        extension = (self.change_datatype_actions.get(output_name) or match.ext).lower()
        dbkey = "?" if match.dbkey == "__input__" else match.dbkey
        if dataset is None:
            dataset = self.export_store.datasets.create(
                self.datatypes_registry,
                self.object_store,
                extension=extension,
                designation=match.designation,
                visible=match.visible,
                dbkey=dbkey,
                name=match.name or match.designation,
                info=info,
                state=state,
                sources=match.sources,
                hashes=match.hashes,
                created_from_basename=match.created_from_basename,
                tags=match.tag_list,
            )
        else:
            dataset.extension = extension
            dataset.designation = match.designation
            dataset.visible = match.visible
            dataset.dbkey = dbkey
            dataset.name = match.name or match.designation
            dataset.info = info
            dataset.state = state
        dataset.apply_uploaded_metadata(metadata or {})
        return dataset

    def store_dataset(self, dataset, discovered_file, output_name, dataset_attributes=None):
        match = discovered_file.match
        dataset_attributes = dataset_attributes or {}
        for attribute_name in ("name", "info", "dbkey"):
            if attribute_name in dataset_attributes:
                setattr(dataset, attribute_name, dataset_attributes[attribute_name])
        if "ext" in dataset_attributes:
            dataset.extension = dataset_attributes["ext"]
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
                persist_extra_files(
                    self.object_store,
                    safe_path_from_directory(match.extra_files, self.job_working_directory),
                    dataset,
                )
                dataset.set_size()
            else:
                dataset.set_size(no_extra_files=True)
        metadata = dataset_attributes.get("metadata")
        dataset.resolve_datatype()
        if metadata:
            metadata = dict(metadata)
            metadata["dbkey"] = dataset_attributes.get("dbkey", dataset.dbkey)
            dataset.metadata.from_JSON_dict(json_dict=metadata)
        else:
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


def unnamed_output_extensions(tool_provided_metadata):
    def walk(elements):
        for element in elements:
            if "elements" in element:
                yield from walk(element["elements"])
            else:
                yield element.get("ext", "data").lower()

    for unnamed_output in tool_provided_metadata.get_unnamed_outputs():
        yield from walk(unnamed_output["elements"])


def discovered_primary_extensions(
    metadata_params,
    tool_provided_metadata,
    dataset_store,
    working_directory,
    input_ext,
):
    for name, output_attributes in metadata_params.get("outputs", {}).items():
        output_definition_dict = metadata_params["tool"]["outputs"].get(name)
        if output_definition_dict is None:
            continue
        output_definition = ToolOutput.from_dict(name, output_definition_dict)
        collectors = [
            dataset_collector(description) for description in output_definition.dataset_collector_descriptions
        ]
        output = dataset_store.find(output_attributes["id"])
        for discovered_file in discover_files(name, tool_provided_metadata, collectors, str(working_directory), output):
            extension = discovered_file.match.ext.lower()
            yield input_ext if extension == "input" else extension


def collect_primary_datasets(context: LightweightJobContext, outputs, input_ext):
    for name, output in outputs.items():
        output_definition = context.output_def(name)
        collectors = (
            [dataset_collector(description) for description in output_definition.dataset_collector_descriptions]
            if output_definition is not None
            else [DEFAULT_DATASET_COLLECTOR]
        )
        discovered_files = list(
            discover_files(name, context.tool_provided_metadata, collectors, context.job_working_directory, output)
        )
        for _discovered_file in discovered_files:
            context.increment_discovered_file_count()
        primary_output_assigned = False
        for index, discovered_file in enumerate(discovered_files):
            match = discovered_file.match
            extension = input_ext if match.ext == "input" else match.ext.lower()
            dbkey = "?" if match.dbkey == "__input__" else match.dbkey
            if index == 0 and discovered_file.collector.assign_primary_output:
                output.change_datatype(extension)
                output.dbkey = dbkey
                output.designation = match.designation
                output.name = match.name or f"{output.name} ({match.designation})"
                output.dataset.external_filename = None
                if not output.dataset.purged:
                    context.object_store.update_from_file(output.dataset, file_name=discovered_file.path, create=True)
                output.init_meta()
                try:
                    output.set_meta()
                except Exception:
                    output.state = "failed_metadata"
                    log.debug("set_meta failed for assigned primary output", exc_info=True)
                output.set_peek()
                primary_output_assigned = True
                continue
            basename = discovered_file.path.rsplit("/", 1)[-1]
            dataset_attributes = context.tool_provided_metadata.get_new_dataset_meta_by_basename(name, basename) or {}
            dataset = context.create_dataset(
                name,
                match,
                context.final_job_state,
                info=output.info,
            )
            dataset.extension = extension
            dataset.dbkey = dbkey
            dataset.name = match.name or f"{output.name} ({match.designation})"
            dataset.init_meta(copy_from=output)
            dataset.dbkey = dbkey
            if output.dataset.purged:
                dataset.purged = True
                dataset.dataset.purged = True
            context.store_dataset(dataset, discovered_file, name, dataset_attributes=dataset_attributes)
            context.add_output_dataset_association(name, [match.designation], dataset)
        if primary_output_assigned:
            output.discovered = True


def _collect_unnamed_hdas(context, elements):
    def walk(current_elements):
        for element in current_elements:
            if "elements" in element:
                yield from walk(element["elements"])
            else:
                yield element

    for element in walk(elements):
        discovered_file = discovered_file_for_element(element, context)
        match = discovered_file.match
        info, state = discovered_file.discovered_state(element, context.final_job_state)
        dataset = context.export_store.datasets.find(match.object_id) if match.object_id else None
        dataset = context.create_dataset(
            None,
            match,
            state,
            info=info,
            metadata=element.get("metadata"),
            dataset=dataset,
        )
        context.store_dataset(dataset, discovered_file, None)


def _collect_unnamed_hdca(context, unnamed_output, output_collections):
    destination = unnamed_output["destination"]
    collection_id = destination.get("object_id")
    if collection_id:
        hdca = context.export_store.dataset_collections.find(collection_id)
        if hdca is None:
            raise ValueError(f"Failed to find target dataset collection [{collection_id}]")
    else:
        if not unnamed_output.get("collection_type"):
            raise RequestParameterInvalidException("Must specify an HDCA collection_type")
        name = unnamed_output.get("name", "unnamed collection")
        hdca = context.export_store.dataset_collections.create(
            name,
            unnamed_output["collection_type"],
            unnamed_output.get("column_definitions"),
        )
        output_collections[name] = hdca
    if error_message := unnamed_output.get("error_message"):
        hdca.collection.handle_population_failed(error_message)
        return
    builder = CollectionElementBuilder(hdca.collection.collection_type)

    def collect(elements, parent_identifiers=None):
        parent_identifiers = parent_identifiers or []
        for element in elements:
            if "elements" in element:
                collect(element["elements"], [*parent_identifiers, element["name"]])
                continue
            discovered_file = discovered_file_for_element(
                element,
                context,
                parent_identifiers=parent_identifiers,
                collector=DEFAULT_DATASET_COLLECTOR,
            )
            match = discovered_file.match
            info, state = discovered_file.discovered_state(element, context.final_job_state)
            dataset = context.create_dataset(
                None,
                match,
                state,
                info=info,
                metadata=element.get("metadata"),
            )
            context.store_dataset(dataset, discovered_file, None)
            builder.add(match.element_identifiers, dataset, row=match.row)

    collect(unnamed_output["elements"])
    hdca.collection.replace_elements(builder.serialize_elements())
    hdca.collection.mark_as_populated()


def collect_dynamic_outputs(context: LightweightJobContext, output_collections):
    for unnamed_output in validate_unnamed_outputs(context):
        for element in unnamed_output["elements"]:
            element_name = element.get("name")
            rows = unnamed_output.get("rows", {})
            if element_name in rows and "row" not in element:
                element["row"] = rows[element_name]
        destination_type = unnamed_output["destination"]["type"]
        if destination_type == "hdas":
            _collect_unnamed_hdas(context, unnamed_output["elements"])
        elif destination_type == "hdca":
            _collect_unnamed_hdca(context, unnamed_output, output_collections)
        else:
            raise ValueError(f"Unsupported lightweight output destination [{destination_type}]")

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
        except OutputCollectionSecurityError:
            collection.handle_population_failed("Problem building datasets for collection.")
            raise
        except Exception:
            log.exception("Problem gathering output collection")
            collection.handle_population_failed("Problem building datasets for collection.")
