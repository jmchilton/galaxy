import abc
import contextlib
import datetime
import os
from json import dump, dumps, load

import six
from boltons.iterutils import remap
from sqlalchemy.orm import eagerload_all
from sqlalchemy.sql import expression

from galaxy.exceptions import MalformedContents, ObjectNotFound
from galaxy.util import FILENAME_VALID_CHARS
from galaxy.util import in_directory
from galaxy.version import VERSION_MAJOR
from .item_attrs import add_item_annotation, get_item_annotation_str
from .. import model

ATTRS_FILENAME_HISTORY = 'history_attrs.txt'
ATTRS_FILENAME_DATASETS = 'datasets_attrs.txt'
ATTRS_FILENAME_JOBS = 'jobs_attrs.txt'
ATTRS_FILENAME_IMPLICIT_COLLECTION_JOBS = 'implicit_collection_jobs_attrs.txt'
ATTRS_FILENAME_COLLECTIONS = 'collections_attrs.txt'
ATTRS_FILENAME_EXPORT = 'export_attrs.txt'


class ImportOptions(object):

    def __init__(self, allow_edit=False):
        self.allow_edit = allow_edit


@six.add_metaclass(abc.ABCMeta)
class ModelImportStore(object):

    def __init__(self, app, user, import_options=None):
        self.app = app
        self.sa_session = app.model.context.current
        self.user = user
        self.import_options = import_options or ImportOptions()

    @abc.abstractmethod
    def defines_new_history(self):
        """Does this store define a new history to create."""

    @abc.abstractmethod
    def new_history_properties(self):
        """Dict of history properties if defines_new_history() is truthy."""

    @abc.abstractmethod
    def datasets_properties(self):
        """Return a list of HDA properties."""

    @abc.abstractmethod
    def collections_properties(self):
        """Return a list of HDCA properties."""

    @abc.abstractmethod
    def jobs_properties(self):
        """Return a list of jobs properties."""

    @abc.abstractproperty
    def object_key(self):
        """Key used to connect objects in metadata.

        Legacy exports used 'hid' but associated objects may not be from the same history
        and a history may contain multiple objects with the same 'hid'.
        """

    @abc.abstractproperty
    def trust_hid(self, obj_attrs):
        """Trust HID when importing objects into a new History."""

    @contextlib.contextmanager
    def target_history(self, default_history=None):
        new_history = None

        if self.defines_new_history():
            history_properties = self.new_history_properties()
            history_name = history_properties.get('name')
            if history_name:
                history_name = 'imported from archive: %s' % history_name
            else:
                history_name = 'unnamed imported history'

            # Create history.
            new_history = model.History(name=history_name,
                                        user=self.user)
            new_history.importing = True
            hid_counter = history_properties.get('hid_counter')
            genome_build = history_properties.get('genome_build')

            # TODO: This seems like it shouldn't be imported, try to test and verify we can calculate this
            # and get away without it. -John
            if hid_counter:
                new_history.hid_counter = hid_counter
            if genome_build:
                new_history.genome_build = genome_build

            self.sa_session.add(new_history)
            self.sa_session.flush()

            if self.user:
                add_item_annotation(self.sa_session, self.user, new_history, history_properties.get('annotation'))

            history = new_history
        else:
            history = default_history

        yield history

        if new_history is not None:
            # Done importing.
            new_history.importing = False
            self.sa_session.flush()

    def perform_import(self, job, history, new_history=False):
        datasets_attrs = self.datasets_properties()

        object_key = self.object_key
        hdas_by_key = {}
        hdcas_by_key = {}
        jobs_by_key = {}

        requires_hid = []

        # Create datasets.
        for dataset_attrs in datasets_attrs:
            if 'id' in dataset_attrs:
                assert self.import_options.allow_edit
                hda = self.sa_session.query(model.HistoryDatasetAssociation).get(dataset_attrs["id"])
                attributes = [
                    "name",
                    "extension",
                    "info",
                    "blurb",
                    "peek",
                    "designation",
                    "visible",
                    "metadata",
                ]
                for attribute in attributes:
                    if attribute in dataset_attrs:
                        setattr(hda, attribute, dataset_attrs[attribute])

                if "dataset" in dataset_attrs:
                    dataset_attributes = [
                        "state",
                        "deleted",
                        "purged",
                        "external_filename",
                        "_extra_files_path",
                        "file_size",
                        "object_store_id",
                        "total_size",
                        "uuid"
                    ]
                    for attribute in dataset_attributes:
                        if attribute in dataset_attrs["dataset"]:
                            setattr(hda.dataset, attribute, dataset_attrs["dataset"][attribute])

                self.sa_session.flush()
            else:
                metadata = dataset_attrs['metadata']

                # Create dataset and HDA.
                hda = model.HistoryDatasetAssociation(name=dataset_attrs['name'],
                                                      extension=dataset_attrs['extension'],
                                                      info=dataset_attrs['info'],
                                                      blurb=dataset_attrs['blurb'],
                                                      peek=dataset_attrs['peek'],
                                                      designation=dataset_attrs['designation'],
                                                      visible=dataset_attrs['visible'],
                                                      deleted=dataset_attrs.get('deleted', False),
                                                      dbkey=metadata['dbkey'],
                                                      metadata=metadata,
                                                      history=history,
                                                      create_dataset=True,
                                                      sa_session=self.sa_session)
                if 'uuid' in dataset_attrs:
                    hda.dataset.uuid = dataset_attrs["uuid"]

                self.sa_session.add(hda)
                self.sa_session.flush()
                # don't use add_history to manage HID handling across full import to try to preserve
                # HID structure.
                hda.history = history
                if new_history and self.trust_hid(dataset_attrs):
                    hda.hid = dataset_attrs['hid']
                else:
                    requires_hid.append(hda)

                self.sa_session.flush()

                file_name = dataset_attrs.get('file_name')
                if file_name:
                    # Do security check and move/copy dataset data.
                    archive_path = os.path.abspath(os.path.join(self.archive_dir, file_name))
                    if os.path.islink(archive_path):
                        raise MalformedContents("Invalid dataset path: %s" % archive_path)

                    temp_dataset_file_name = \
                        os.path.realpath(archive_path)

                    if not in_directory(temp_dataset_file_name, self.archive_dir):
                        raise MalformedContents("Invalid dataset path: %s" % temp_dataset_file_name)

                if not file_name or not os.path.exists(temp_dataset_file_name):
                    hda.state = hda.states.DISCARDED
                    hda.deleted = True
                    hda.purged = True
                else:
                    hda.state = hda.states.OK
                    self.app.object_store.update_from_file(hda.dataset, file_name=temp_dataset_file_name, create=True)

                    # Import additional files if present. Histories exported previously might not have this attribute set.
                    dataset_extra_files_path = dataset_attrs.get('extra_files_path', None)
                    if dataset_extra_files_path:
                        try:
                            file_list = os.listdir(os.path.join(self.archive_dir, dataset_extra_files_path))
                        except OSError:
                            file_list = []

                        if file_list:
                            for extra_file in file_list:
                                self.app.object_store.update_from_file(
                                    hda.dataset, extra_dir='dataset_%s_files' % hda.dataset.id,
                                    alt_name=extra_file, file_name=os.path.join(self.archive_dir, dataset_extra_files_path, extra_file),
                                    create=True)
                    hda.dataset.set_total_size()  # update the filesize record in the database

                if self.user:
                    add_item_annotation(self.sa_session, self.user, hda, dataset_attrs['annotation'])
                    # TODO: Set tags.

                self.app.datatypes_registry.set_external_metadata_tool.regenerate_imported_metadata_if_needed(
                    hda, history, job
                )

                hdas_by_key[dataset_attrs[object_key]] = hda

        #
        # Create collections.
        #
        collections_attrs = self.collections_properties()

        def import_collection(collection_attrs):
            def materialize_elements(dc):
                if "elements" not in collection_attrs:
                    return

                elements_attrs = collection_attrs['elements']
                for element_attrs in elements_attrs:
                    dce = model.DatasetCollectionElement(collection=dc,
                                                         element=model.DatasetCollectionElement.UNINITIALIZED_ELEMENT,
                                                         element_index=element_attrs['element_index'],
                                                         element_identifier=element_attrs['element_identifier'])
                    if 'hda' in element_attrs:
                        hda_attrs = element_attrs['hda']
                        hda_key = hda_attrs[object_key]
                        hda = hdas_by_key[hda_key]
                        dce.hda = hda
                    elif 'child_collection' in element_attrs:
                        dce.child_collection = import_collection(element_attrs['child_collection'])
                    else:
                        raise Exception("Unknown collection element type encountered.")

                    self.sa_session.add(dce)

            if "id" in collection_attrs:
                assert self.import_options.allow_edit
                dc = self.sa_session.query(model.DatasetCollection).get(collection_attrs["id"])
                attributes = [
                    "collection_type",
                    "populated_state",
                    "element_count",
                ]
                for attribute in attributes:
                    if attribute in collection_attrs:
                        setattr(dc, attribute, collection_attrs[attribute])
                materialize_elements(dc)
            else:
                # create collection
                dc = model.DatasetCollection(collection_type=collection_attrs['type'])
                dc.populated_state = collection_attrs["populated_state"]
                # TODO: element_count...
                materialize_elements(dc)

            self.sa_session.add(dc)
            return dc

        for collection_attrs in collections_attrs:
            dc = import_collection(collection_attrs["collection"])
            if "id" in collection_attrs:
                pass
            else:
                hdca = model.HistoryDatasetCollectionAssociation(collection=dc,
                                                                 visible=True,
                                                                 name=collection_attrs['display_name'])
                hdca.history = history
                if new_history and self.trust_hid(collection_attrs):
                    hdca.hid = collection_attrs['hid']
                else:
                    requires_hid.append(hdca)

                self.sa_session.add(hdca)
                hdcas_by_key[collection_attrs[object_key]] = hdca

        # assign HIDs for newly created objects that didn't match original history
        requires_hid_len = len(requires_hid)
        if requires_hid_len > 0:
            base = history._next_hid(n=requires_hid_len)
            for i, obj in enumerate(requires_hid):
                obj.hid = base + i

        self.sa_session.flush()
        #
        # Create jobs.
        #
        jobs_attrs = self.jobs_properties()

        # Create each job.
        for job_attrs in jobs_attrs:
            imported_job = model.Job()
            imported_job.user = self.user
            # TODO: set session?
            # imported_job.session = trans.get_galaxy_session().id
            imported_job.history = history
            imported_job.imported = True
            imported_job.tool_id = job_attrs['tool_id']
            imported_job.tool_version = job_attrs['tool_version']
            imported_job.set_state(job_attrs['state'])
            imported_job.info = job_attrs.get('info', None)
            imported_job.exit_code = job_attrs.get('exit_code', None)
            imported_job.traceback = job_attrs.get('traceback', None)
            imported_job.stdout = job_attrs.get('stdout', None)
            imported_job.stderr = job_attrs.get('stderr', None)
            imported_job.command_line = job_attrs.get('command_line', None)
            try:
                imported_job.create_time = datetime.datetime.strptime(job_attrs["create_time"], "%Y-%m-%dT%H:%M:%S.%f")
                imported_job.update_time = datetime.datetime.strptime(job_attrs["update_time"], "%Y-%m-%dT%H:%M:%S.%f")
            except Exception:
                pass
            self.sa_session.add(imported_job)
            self.sa_session.flush()

            # Connect jobs to input and output datasets.
            params = self._normalize_job_parameters(imported_job, job_attrs, hdas_by_key, hdcas_by_key)
            for name, value in params.items():
                # Transform parameter values when necessary.
                imported_job.add_parameter(name, dumps(value))

            self._connect_outputs(imported_job, job_attrs, hdas_by_key, hdcas_by_key)
            self._connect_inputs(imported_job, job_attrs, hdas_by_key, hdcas_by_key)
            self.sa_session.flush()

            if object_key in job_attrs:
                jobs_by_key[job_attrs[object_key]] = imported_job

        implicit_collection_jobs_attrs = self.implicit_collection_jobs_properties()
        for icj_attrs in implicit_collection_jobs_attrs:
            icj = model.ImplicitCollectionJobs()
            icj.populated_state = icj_attrs["populated_state"]

            icj.jobs = []
            for order_index, job in enumerate(icj_attrs["jobs"]):
                icja = model.ImplicitCollectionJobsJobAssociation()
                icja.implicit_collection_jobs = icj
                icja.job = jobs_by_key[job]
                icja.order_index = order_index
                icj.jobs.append(icja)
                self.sa_session.add(icja)

            self.sa_session.add(icj)
            self.sa_session.flush()

        self.sa_session.flush()


def get_import_model_store(app, user, archive_dir, import_options=None):
    assert os.path.isdir(archive_dir)
    if os.path.exists(os.path.join(archive_dir, ATTRS_FILENAME_EXPORT)):
        return DirectoryImportModelStoreLatest(app, user, archive_dir, import_options=import_options)
    else:
        return DirectoryImportModelStore1901(app, user, archive_dir, import_options=import_options)


class BaseDirectoryImportModelStore(ModelImportStore):

    def defines_new_history(self):
        new_history_attributes = os.path.join(self.archive_dir, ATTRS_FILENAME_HISTORY)
        return os.path.exists(new_history_attributes)

    def new_history_properties(self):
        new_history_attributes = os.path.join(self.archive_dir, ATTRS_FILENAME_HISTORY)
        history_properties = load(open(new_history_attributes))
        return history_properties

    def datasets_properties(self):
        datasets_attrs_file_name = os.path.join(self.archive_dir, ATTRS_FILENAME_DATASETS)
        datasets_attrs = load(open(datasets_attrs_file_name))
        provenance_file_name = datasets_attrs_file_name + ".provenance"

        if os.path.exists(provenance_file_name):
            provenance_attrs = load(open(provenance_file_name))
            datasets_attrs += provenance_attrs

        return datasets_attrs

    def collections_properties(self):
        collections_attrs_file_name = os.path.join(self.archive_dir, ATTRS_FILENAME_COLLECTIONS)
        if os.path.exists(collections_attrs_file_name):
            collections_attrs = load(open(collections_attrs_file_name))
        else:
            collections_attrs = []
        return collections_attrs

    def jobs_properties(self):
        jobs_attr_file_name = os.path.join(self.archive_dir, ATTRS_FILENAME_JOBS)
        jobs_attrs = load(open(jobs_attr_file_name))
        return jobs_attrs

    def implicit_collection_jobs_properties(self):
        implicit_collection_jobs_attrs_file_name = os.path.join(self.archive_dir, ATTRS_FILENAME_IMPLICIT_COLLECTION_JOBS)
        if os.path.exists(implicit_collection_jobs_attrs_file_name):
            implicit_collection_jobs_attrs = load(open(implicit_collection_jobs_attrs_file_name))
        else:
            implicit_collection_jobs_attrs = []
        return implicit_collection_jobs_attrs


class DirectoryImportModelStore1901(BaseDirectoryImportModelStore):
    object_key = 'hid'

    def __init__(self, app, user, archive_dir, import_options=None):
        super(DirectoryImportModelStore1901, self).__init__(app, user, import_options=import_options)
        archive_dir = os.path.realpath(archive_dir)

        # Bioblend previous to 17.01 exported histories with an extra subdir.
        if not os.path.exists(os.path.join(archive_dir, ATTRS_FILENAME_HISTORY)):
            for d in os.listdir(archive_dir):
                if os.path.isdir(os.path.join(archive_dir, d)):
                    archive_dir = os.path.join(archive_dir, d)
                    break

        self.archive_dir = archive_dir

    def _connect_outputs(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        for output_key in job_attrs['output_datasets']:
            output_hda = hdas_by_key[output_key]
            if output_hda:
                imported_job.add_output_dataset(output_hda.name, output_hda)

    def _connect_inputs(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        if 'input_mapping' in job_attrs:
            for input_name, input_key in job_attrs['input_mapping'].items():
                input_hda = hdas_by_key[input_key]
                if input_hda:
                    imported_job.add_input_dataset(input_name, input_hda)

    def _normalize_job_parameters(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        def remap_objects(p, k, obj):
            if isinstance(obj, dict) and obj.get('__HistoryDatasetAssociation__', False):
                return (k, hdas_by_key[obj[self.object_key]].id)
            return (k, obj)

        params = job_attrs['params']
        params = remap(params, remap_objects)
        return params

    def trust_hid(self, obj_attrs):
        # We didn't do object tracking so we pretty much have to trust the HID and accept
        # that it will be wrong a lot.
        return True


class DirectoryImportModelStoreLatest(BaseDirectoryImportModelStore):
    object_key = 'encoded_id'

    def __init__(self, app, user, archive_dir, import_options=None):
        super(DirectoryImportModelStoreLatest, self).__init__(app, user, import_options=import_options)
        archive_dir = os.path.realpath(archive_dir)
        self.archive_dir = archive_dir
        if self.defines_new_history():
            self.import_history_encoded_id = self.new_history_properties().get("encoded_id")
        else:
            self.import_history_encoded_id = None

    def _connect_inputs(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        if 'input_dataset_mapping' in job_attrs:
            for input_name, input_keys in job_attrs['input_dataset_mapping'].items():
                input_keys = input_keys or []
                for input_key in input_keys:
                    input_hda = hdas_by_key[input_key] or []
                    if input_hda:
                        imported_job.add_input_dataset(input_name, input_hda)

        if 'input_dataset_collection_mapping' in job_attrs:
            for input_name, input_keys in job_attrs['input_dataset_collection_mapping'].items():
                input_keys = input_keys or []
                for input_key in input_keys:
                    input_hdca = hdcas_by_key[input_key] or []
                    if input_hdca:
                        imported_job.add_input_dataset_collection(input_name, input_hdca)

    def _connect_outputs(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        if 'output_dataset_mapping' in job_attrs:
            for output_name, output_keys in job_attrs['output_dataset_mapping'].items():
                output_keys = output_keys or []
                for output_key in output_keys:
                    output_hda = hdas_by_key[output_key] or []
                    if output_hda:
                        imported_job.add_output_dataset(output_name, output_hda)

        if 'output_dataset_collection_mapping' in job_attrs:
            for output_name, output_keys in job_attrs['output_dataset_collection_mapping'].items():
                output_keys = output_keys or []
                for output_key in output_keys:
                    output_hdca = hdcas_by_key[output_key] or []
                    if output_hdca:
                        imported_job.add_output_dataset_collection(output_name, output_hdca)

    def trust_hid(self, obj_attrs):
        return self.import_history_encoded_id and obj_attrs.get("history_encoded_id") == self.import_history_encoded_id

    def _normalize_job_parameters(self, imported_job, job_attrs, hdas_by_key, hdcas_by_key):
        def remap_objects(p, k, obj):
            if isinstance(obj, dict) and obj.get('model_class', None) == "HistoryDatasetAssociation":
                return (k, hdas_by_key[obj[self.object_key]].id)
            if isinstance(obj, dict) and obj.get('model_class', None) == "HistoryDatasetCollectionAssociation":
                return (k, hdcas_by_key[obj[self.object_key]].id)
            return (k, obj)

        params = job_attrs['params']
        params = remap(params, remap_objects)
        return params


class ModelExportStore(object):

    def __init__(self, app, export_directory, for_edit=False):
        self.app = app
        self.export_directory = export_directory
        self.serialization_options = model.SerializationOptions(
            for_edit=for_edit,
            serialize_files_handler=self,
        )
        self.included_datasets = {}
        self.included_collections = []
        self.collection_datasets = {}
        self.collections_attrs = []

    def serialize_files(self, dataset, as_dict):
        export_directory = self.export_directory
        if dataset.id in self.included_datasets:
            file_name, extra_files_path = None, None
            try:
                _file_name = dataset.file_name
                if os.path.exists(_file_name):
                    file_name = _file_name
            except ObjectNotFound:
                pass

            if dataset.extra_files_path_exists():
                extra_files_path = dataset.extra_files_path
            else:
                pass

        dir_name = 'datasets'
        dir_path = os.path.join(export_directory, dir_name)
        dataset_hid = as_dict['hid']
        assert dataset_hid, as_dict

        if file_name:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

            target_filename = get_export_dataset_filename(as_dict['name'], as_dict['extension'], dataset_hid)
            arcname = os.path.join(dir_name, target_filename)

            src = file_name
            dest = os.path.join(export_directory, arcname)
            os.symlink(src, dest)
            as_dict['file_name'] = arcname

        if extra_files_path:
            try:
                file_list = os.listdir(extra_files_path)
            except OSError:
                file_list = []

            if len(file_list):
                arcname = os.path.join(dir_name, 'extra_files_path_%s' % dataset_hid)
                os.symlink(extra_files_path, os.path.join(export_directory, arcname))
                as_dict['extra_files_path'] = arcname
            else:
                as_dict['extra_files_path'] = ''

    def exported_key(self, app, obj):
        return app.security.encode_id(obj.id, kind='model_export')

    def __enter__(self):
        return self

    def export_history(self, history, include_hidden=False, include_deleted=False):
        app = self.app
        export_directory = self.export_directory

        history_attrs = history.serialize(app, self.serialization_options)
        history_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_HISTORY)
        with open(history_attrs_filename, 'w') as history_attrs_out:
            dump(history_attrs, history_attrs_out)

        sa_session = app.model.context.current

        # Write collections' attributes (including datasets list) to file.
        query = (sa_session.query(model.HistoryDatasetCollectionAssociation)
                 .filter(model.HistoryDatasetCollectionAssociation.history == history)
                 .filter(model.HistoryDatasetCollectionAssociation.deleted == expression.false()))
        collections = query.all()

        for collection in collections:
            # filter this ?
            if not collection.populated:
                break
            if collection.state != 'ok':
                break

            self.add_dataset_collection(collection)

            # export jobs for these datasets
            for collection_dataset in collection.dataset_instances:
                if collection_dataset.deleted and not include_deleted:
                    include_files = False
                else:
                    include_files = True

                self.add_dataset(collection_dataset, include_files=include_files)
                self.collection_datasets[collection_dataset.id] = True

        # Write datasets' attributes to file.
        query = (sa_session.query(model.HistoryDatasetAssociation)
                 .filter(model.HistoryDatasetAssociation.history == history)
                 .join("dataset")
                 .options(eagerload_all("dataset.actions"))
                 .order_by(model.HistoryDatasetAssociation.hid)
                 .filter(model.Dataset.purged == expression.false()))
        datasets = query.all()
        for dataset in datasets:
            dataset.annotation = get_item_annotation_str(sa_session, history.user, dataset)
            add_dataset = (not dataset.visible or not include_hidden) and (not dataset.deleted or include_deleted)
            if dataset.id in self.collection_datasets:
                add_dataset = True

            if dataset.id not in self.included_datasets:
                self.add_dataset(dataset, include_files=add_dataset)

    def add_dataset_collection(self, collection):
        self.collections_attrs.append(collection)
        self.included_collections.append(collection)

    def add_dataset(self, dataset, include_files=True):
        self.included_datasets[dataset.id] = (dataset, include_files)

    def _finalize(self):
        app = self.app
        export_directory = self.export_directory

        datasets_attrs = []
        provenance_attrs = []
        for dataset_id, (dataset, include_files) in self.included_datasets.items():
            if include_files:
                datasets_attrs.append(dataset)
            else:
                provenance_attrs.append(dataset)

        datasets_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_DATASETS)
        with open(datasets_attrs_filename, 'w') as datasets_attrs_out:
            dump(list(map(lambda d: d.serialize(app, self.serialization_options), datasets_attrs)), datasets_attrs_out)

        with open(datasets_attrs_filename + ".provenance", 'w') as provenance_attrs_out:
            dump(list(map(lambda d: d.serialize(app, self.serialization_options), provenance_attrs)), provenance_attrs_out)

        collections_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_COLLECTIONS)
        with open(collections_attrs_filename, 'w') as collections_attrs_out:
            dump(list(map(lambda d: d.serialize(app, self.serialization_options), self.collections_attrs)), collections_attrs_out)

        #
        # Write jobs attributes file.
        #

        # Get all jobs associated with included HDAs.
        jobs_dict = {}
        implicit_collection_jobs_dict = {}

        def record_associated_jobs(obj):
            # Get the job object.
            job = None
            for assoc in obj.creating_job_associations:
                job = assoc.job
                break
            if not job:
                # No viable job.
                return

            jobs_dict[job.id] = job
            icja = job.implicit_collection_jobs_association
            if icja:
                implicit_collection_jobs = icja.implicit_collection_jobs
                implicit_collection_jobs_dict[implicit_collection_jobs.id] = implicit_collection_jobs

        for hda_id, (hda, include_files) in self.included_datasets.items():
            # Get the associated job, if any. If this hda was copied from another,
            # we need to find the job that created the origial hda
            job_hda = hda
            while job_hda.copied_from_history_dataset_association:  # should this check library datasets as well?
                job_hda = job_hda.copied_from_history_dataset_association
            if not job_hda.creating_job_associations:
                # No viable HDA found.
                continue

            record_associated_jobs(job_hda)

        for hdca in self.included_collections:
            record_associated_jobs(hdca)

        # Get jobs' attributes.
        jobs_attrs = []
        for id, job in jobs_dict.items():
            # Don't attempt to serialize jobs for editing... yet at least.
            if self.serialization_options.for_edit:
                continue

            job_attrs = job.serialize(app, self.serialization_options)

            # -- Get input, output datasets. --

            input_dataset_mapping = {}
            output_dataset_mapping = {}
            input_dataset_collection_mapping = {}
            output_dataset_collection_mapping = {}
            implicit_output_dataset_collection_mapping = {}

            for assoc in job.input_datasets:
                # Optional data inputs will not have a dataset.
                if assoc.dataset:
                    name = assoc.name
                    if name not in input_dataset_mapping:
                        input_dataset_mapping[name] = []

                    input_dataset_mapping[name].append(self.exported_key(app, assoc.dataset))

            for assoc in job.output_datasets:
                # Optional data inputs will not have a dataset.
                if assoc.dataset:
                    name = assoc.name
                    if name not in output_dataset_mapping:
                        output_dataset_mapping[name] = []

                    output_dataset_mapping[name].append(self.exported_key(app, assoc.dataset))

            for assoc in job.input_dataset_collections:
                # Optional data inputs will not have a dataset.
                if assoc.dataset_collection:
                    name = assoc.name
                    if name not in input_dataset_collection_mapping:
                        input_dataset_collection_mapping[name] = []

                    input_dataset_collection_mapping[name].append(self.exported_key(app, assoc.dataset_collection))

            for assoc in job.output_dataset_collection_instances:
                # Optional data outputs will not have a dataset.
                if assoc.dataset_collection_instance:
                    name = assoc.name
                    if name not in output_dataset_collection_mapping:
                        output_dataset_collection_mapping[name] = []

                    output_dataset_collection_mapping[name].append(self.exported_key(app, assoc.dataset_collection_instance))

            for assoc in job.output_dataset_collections:
                if assoc.dataset_collection:
                    name = assoc.name

                    if name not in implicit_output_dataset_collection_mapping:
                        implicit_output_dataset_collection_mapping[name] = []

                    implicit_output_dataset_collection_mapping[name].append(self.exported_key(app, assoc.dataset_collection))

            job_attrs['input_dataset_mapping'] = input_dataset_mapping
            job_attrs['input_dataset_collection_mapping'] = input_dataset_collection_mapping
            job_attrs['output_dataset_mapping'] = output_dataset_mapping
            job_attrs['output_dataset_collection_mapping'] = output_dataset_collection_mapping
            job_attrs['implicit_output_dataset_collection_mapping'] = implicit_output_dataset_collection_mapping

            jobs_attrs.append(job_attrs)

        icjs_attrs = []
        for icj_id, icj in implicit_collection_jobs_dict.items():
            icj_attrs = icj.serialize(app, self.serialization_options)
            icjs_attrs.append(icj_attrs)

        jobs_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_JOBS)
        with open(jobs_attrs_filename, 'w') as jobs_attrs_out:
            dump(jobs_attrs, jobs_attrs_out)

        icjs_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_IMPLICIT_COLLECTION_JOBS)
        with open(icjs_attrs_filename, 'w') as icjs_attrs_out:
            dump(icjs_attrs, icjs_attrs_out)

        export_attrs_filename = os.path.join(export_directory, ATTRS_FILENAME_EXPORT)
        with open(export_attrs_filename, 'w') as export_attrs_out:
            dump({"galaxy_version": VERSION_MAJOR}, export_attrs_out)

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self._finalize()
        # http://effbot.org/zone/python-with-statement.htm
        return isinstance(exc_val, TypeError)


def get_export_dataset_filename(name, ext, hid):
    """
    Builds a filename for a dataset using its name an extension.
    """
    base = ''.join(c in FILENAME_VALID_CHARS and c or '_' for c in name)
    return base + "_%s.%s" % (hid, ext)
