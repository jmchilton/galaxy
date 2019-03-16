"""Utilities for discovering files to add to a model store.

Working with input "JSON" format used for Fetch API, galaxy.json
imports, etc... High-level utilities in this file can be used during
job output discovery or for persisting Galaxy model objects
corresponding to files in other contexts.
"""
import os
from collections import namedtuple

import galaxy.model
from galaxy import util
from galaxy.exceptions import (
    RequestParameterInvalidException
)


UNSET = object()


class ModelPersistenceContext(object):
    """Class for creating datasets while finding files.

    This class takes care of populating metadata required for datasets and other potential
    model objects.
    """

    def create_dataset(
        self,
        ext,
        designation,
        visible,
        dbkey,
        name,
        filename,
        metadata_source_name=None,
        info=None,
        library_folder=None,
        link_data=False,
        primary_data=None,
        init_from=None,
        dataset_attributes=None,
        tag_list=[],
        sources=[],
        hashes=[],
    ):
        sa_session = self.sa_session

        # You can initialize a dataset or initialize from a dataset but not both.
        if init_from:
            assert primary_data is None
        if primary_data:
            assert init_from is None

        if metadata_source_name:
            assert init_from is None
        if init_from:
            assert metadata_source_name is None

        if primary_data is not None:
            primary_data.extension = ext
            primary_data.visible = visible
            primary_data.dbkey = dbkey
        else:
            if not library_folder:
                primary_data = galaxy.model.HistoryDatasetAssociation(extension=ext,
                                                                      designation=designation,
                                                                      visible=visible,
                                                                      dbkey=dbkey,
                                                                      create_dataset=True,
                                                                      flush=False,
                                                                      sa_session=sa_session)

                self.persist_object(primary_data)
                if init_from:
                    self.permission_provider.copy_dataset_permissions(init_from, primary_data)
                    primary_data.state = init_from.state
                else:
                    self.permission_provider.set_default_hda_permissions(primary_data)
            else:
                ld = galaxy.model.LibraryDataset(folder=library_folder, name=name)
                ldda = galaxy.model.LibraryDatasetDatasetAssociation(name=name,
                                                                     extension=ext,
                                                                     dbkey=dbkey,
                                                                     # library_dataset=ld,
                                                                     user=self.user,
                                                                     create_dataset=True,
                                                                     flush=False,
                                                                     sa_session=sa_session)
                ld.library_dataset_dataset_association = ldda
                ldda.raw_set_dataset_state(ldda.states.OK)

                self.add_library_dataset_to_folder(library_folder, ld)
                primary_data = ldda

        for source_dict in sources:
            source = galaxy.model.DatasetSource()
            source.source_uri = source_dict["source_uri"]
            primary_data.dataset.sources.append(source)

        for hash_dict in hashes:
            hash_object = galaxy.model.DatasetHash()
            hash_object.hash_function = hash_dict["hash_function"]
            hash_object.hash_value = hash_dict["hash_value"]
            primary_data.dataset.hashes.append(hash_object)

        self.flush()

        if tag_list:
            self.tag_handler.add_tags_from_list(self.job.user, primary_data, tag_list)

        # Move data from temp location to dataset location
        if not link_data:
            self.object_store.update_from_file(primary_data.dataset, file_name=filename, create=True)
        else:
            primary_data.link_to(filename)

        # We are sure there are no extra files, so optimize things that follow by settting total size also.
        primary_data.set_size(no_extra_files=True)
        # If match specified a name use otherwise generate one from
        # designation.
        primary_data.name = name

        # Copy metadata from one of the inputs if requested.
        if metadata_source_name:
            metadata_source = self.metadata_source_provider.get_metadata_source(metadata_source_name)
            primary_data.init_meta(copy_from=metadata_source)
        elif init_from:
            metadata_source = init_from
            primary_data.init_meta(copy_from=init_from)
            # when coming from primary dataset - respect pattern of output - this makes sense
            primary_data.dbkey = dbkey
        else:
            primary_data.init_meta()

        if info is not None:
            primary_data.info = info

        # add tool/metadata provided information
        dataset_attributes = dataset_attributes or {}
        if dataset_attributes:
            # TODO: discover_files should produce a match that encorporates this -
            # would simplify ToolProvidedMetadata interface and eliminate this
            # crap path.
            dataset_att_by_name = dict(ext='extension')
            for att_set in ['name', 'info', 'ext', 'dbkey']:
                dataset_att_name = dataset_att_by_name.get(att_set, att_set)
                setattr(primary_data, dataset_att_name, dataset_attributes.get(att_set, getattr(primary_data, dataset_att_name)))

        metadata_dict = dataset_attributes.get('metadata', None)
        if metadata_dict:
            if "dbkey" in dataset_attributes:
                metadata_dict["dbkey"] = dataset_attributes["dbkey"]
            # branch tested with tool_provided_metadata_3 / tool_provided_metadata_10
            primary_data.metadata.from_JSON_dict(json_dict=metadata_dict)
        else:
            primary_data.set_meta()

        primary_data.set_peek()

        return primary_data


class UnusedPermissionProvider(object):

    @property
    def permissions(self):
        return UNSET

    def set_default_hda_permissions(self, primary_data):
        return

    def copy_dataset_permissions(self, init_from, primary_data):
        raise NotImplementedError()


class UnusedMetadataSourceProvider(object):

    def get_metadata_source(self, input_name):
        raise NotImplementedError()


class SessionlessModelPersistenceContext(ModelPersistenceContext):

    def __init__(self, object_store, export_store, working_directory, input_dbkey="?"):
        self.permission_provider = UnusedPermissionProvider()
        self.metadata_source_provider = UnusedMetadataSourceProvider()
        # Passed to datasetinstance constructors...
        self.sa_session = None
        self.object_store = object_store
        self.export_store = export_store

        self.job_working_directory = working_directory  # TODO: rename...

    @property
    def tag_handler(self):
        raise NotImplementedError()

    @property
    def user(self):
        return None

    def add_output_dataset_association(self, name, dataset):
        raise NotImplementedError()

    def add_library_dataset_to_folder(self, library_folder, ld):
        library_folder.datasets.append(ld)
        ld.order_id = library_folder.item_count
        library_folder.item_count += 1

    def create_library_folder(self, parent_folder, name, description):
        nested_folder = galaxy.model.LibraryFolder(name=name, description=description, order_id=parent_folder.item_count)
        parent_folder.item_count += 1
        parent_folder.folders.append(nested_folder)
        return nested_folder

    def add_datasets_to_history(self, datasets, for_output_dataset=None):
        if for_output_dataset is not None:
            raise NotImplementedError()

        for dataset in datasets:
            self.export_store.add_dataset(dataset)

    def persist_object(self, obj):
        pass

    def flush(self):
        pass


def persist_target_to_export_store(target_dict, export_store, object_store, work_directory):
    replace_request_syntax_sugar(target_dict)
    model_persistence_context = SessionlessModelPersistenceContext(object_store, export_store, work_directory)

    assert "destination" in target_dict
    assert "elements" in target_dict
    destination = target_dict["destination"]
    elements = target_dict["elements"]

    assert "type" in destination
    destination_type = destination["type"]

    assert destination_type in ["library", "hdas"]
    if destination_type == "library":
        name = get_required_item(destination, "name", "Must specify a library name")
        description = destination.get("description", "")
        synopsis = destination.get("synopsis", "")
        root_folder = galaxy.model.LibraryFolder(name=name, description='')
        library = galaxy.model.Library(
            name=name,
            description=description,
            synopsis=synopsis,
            root_folder=root_folder,
        )
        persist_elements_to_folder(model_persistence_context, elements, root_folder)
        export_store.export_library(library)
    elif destination_type == "hdas":
        persist_hdas(elements, model_persistence_context)


def persist_elements_to_folder(model_persistence_context, elements, library_folder):
    for element in elements:
        if "elements" in element:
            assert "name" in element
            name = element["name"]
            description = element.get("description")
            nested_folder = model_persistence_context.create_library_folder(library_folder, name, description)
            persist_elements_to_folder(model_persistence_context, element["elements"], nested_folder)
        else:
            discovered_file = discovered_file_for_unnamed_output(element, model_persistence_context.job_working_directory)
            fields_match = discovered_file.match
            designation = fields_match.designation
            visible = fields_match.visible
            ext = fields_match.ext
            dbkey = fields_match.dbkey
            info = element.get("info", None)
            link_data = discovered_file.match.link_data

            # Create new primary dataset
            name = fields_match.name or designation

            sources = fields_match.sources
            hashes = fields_match.hashes
            model_persistence_context.create_dataset(
                ext=ext,
                designation=designation,
                visible=visible,
                dbkey=dbkey,
                name=name,
                filename=discovered_file.path,
                info=info,
                library_folder=library_folder,
                link_data=link_data,
                sources=sources,
                hashes=hashes,
            )


def persist_hdas(elements, model_persistence_context):
    # discover files as individual datasets for the target history
    datasets = []

    def collect_elements_for_history(elements):
        for element in elements:
            if "elements" in element:
                collect_elements_for_history(element["elements"])
            else:
                discovered_file = discovered_file_for_unnamed_output(element, model_persistence_context.job_working_directory)
                fields_match = discovered_file.match
                designation = fields_match.designation
                ext = fields_match.ext
                dbkey = fields_match.dbkey
                info = element.get("info", None)
                link_data = discovered_file.match.link_data

                # Create new primary dataset
                name = fields_match.name or designation

                hda_id = discovered_file.match.object_id
                primary_dataset = None
                if hda_id:
                    primary_dataset = model_persistence_context.sa_session.query(galaxy.model.HistoryDatasetAssociation).get(hda_id)

                sources = fields_match.sources
                hashes = fields_match.hashes
                dataset = model_persistence_context.create_dataset(
                    ext=ext,
                    designation=designation,
                    visible=True,
                    dbkey=dbkey,
                    name=name,
                    filename=discovered_file.path,
                    info=info,
                    link_data=link_data,
                    primary_data=primary_dataset,
                    sources=sources,
                    hashes=hashes,
                )
                dataset.raw_set_dataset_state('ok')
                if not hda_id:
                    datasets.append(dataset)

    collect_elements_for_history(elements)
    model_persistence_context.add_datasets_to_history(datasets)

    def add_datasets_to_history(self, datasets, for_output_dataset=None):
        if for_output_dataset is not None:
            raise NotImplementedError()

        for dataset in datasets:
            self.export_store.add_dataset(dataset)

    def persist_object(self, obj):
        pass

    def flush(self):
        pass


def get_required_item(from_dict, key, message):
    if key not in from_dict:
        raise RequestParameterInvalidException(message)
    return from_dict[key]


def validate_and_normalize_target(obj):
    replace_request_syntax_sugar(obj)


def replace_request_syntax_sugar(obj):
    # For data libraries and hdas to make sense - allow items and items_from in place of elements
    # and elements_from. This is destructive and modifies the supplied request.
    if isinstance(obj, list):
        for el in obj:
            replace_request_syntax_sugar(el)
    elif isinstance(obj, dict):
        if "items" in obj:
            obj["elements"] = obj["items"]
            del obj["items"]
        if "items_from" in obj:
            obj["elements_from"] = obj["items_from"]
            del obj["items_from"]
        for value in obj.values():
            replace_request_syntax_sugar(value)


DiscoveredFile = namedtuple('DiscoveredFile', ['path', 'collector', 'match'])


def discovered_file_for_unnamed_output(dataset, job_working_directory, parent_identifiers=[]):
    target_directory = discover_target_directory(None, job_working_directory)
    filename = dataset["filename"]
    # handle link_data_only here, verify filename is in directory if not linking...
    if not dataset.get("link_data_only"):
        path = os.path.join(target_directory, filename)
        if not util.in_directory(path, target_directory):
            raise Exception("Problem with tool configuration, attempting to pull in datasets from outside working directory.")
    else:
        path = filename
    return DiscoveredFile(path, None, JsonCollectedDatasetMatch(dataset, None, filename, path=path, parent_identifiers=parent_identifiers))


def discover_target_directory(dir_name, job_working_directory):
    if dir_name:
        directory = os.path.join(job_working_directory, dir_name)
        if not util.in_directory(directory, job_working_directory):
            raise Exception("Problem with tool configuration, attempting to pull in datasets from outside working directory.")
        return directory
    else:
        return job_working_directory


class JsonCollectedDatasetMatch(object):

    def __init__(self, as_dict, collector, filename, path=None, parent_identifiers=[]):
        self.as_dict = as_dict
        self.collector = collector
        self.filename = filename
        self.path = path
        self._parent_identifiers = parent_identifiers

    @property
    def designation(self):
        # If collecting nested collection, grab identifier_0,
        # identifier_1, etc... and join on : to build designation.
        element_identifiers = self.raw_element_identifiers
        if element_identifiers:
            return ":".join(element_identifiers)
        elif "designation" in self.as_dict:
            return self.as_dict.get("designation")
        elif "name" in self.as_dict:
            return self.as_dict.get("name")
        else:
            return None

    @property
    def element_identifiers(self):
        return self._parent_identifiers + (self.raw_element_identifiers or [self.designation])

    @property
    def raw_element_identifiers(self):
        identifiers = []
        i = 0
        while True:
            key = "identifier_%d" % i
            if key in self.as_dict:
                identifiers.append(self.as_dict.get(key))
            else:
                break
            i += 1

        return identifiers

    @property
    def name(self):
        """ Return name or None if not defined by the discovery pattern.
        """
        return self.as_dict.get("name")

    @property
    def dbkey(self):
        return self.as_dict.get("dbkey", getattr(self.collector, "default_dbkey", "?"))

    @property
    def ext(self):
        return self.as_dict.get("ext", getattr(self.collector, "default_ext", "data"))

    @property
    def visible(self):
        try:
            return self.as_dict["visible"].lower() == "visible"
        except KeyError:
            return getattr(self.collector, "default_visible", True)

    @property
    def link_data(self):
        return bool(self.as_dict.get("link_data_only", False))

    @property
    def tag_list(self):
        return self.as_dict.get("tags", [])

    @property
    def object_id(self):
        return self.as_dict.get("object_id", None)

    @property
    def sources(self):
        return self.as_dict.get("sources", [])

    @property
    def hashes(self):
        return self.as_dict.get("hashes", [])


class RegexCollectedDatasetMatch(JsonCollectedDatasetMatch):

    def __init__(self, re_match, collector, filename, path=None):
        super(RegexCollectedDatasetMatch, self).__init__(
            re_match.groupdict(), collector, filename, path=path
        )
