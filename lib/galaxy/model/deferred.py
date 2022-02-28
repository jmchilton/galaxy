import abc
import logging
import os
import shutil
from typing import (
    NamedTuple,
    Optional,
    Union,
)

from sqlalchemy.orm import object_session
from sqlalchemy.orm.exc import DetachedInstanceError
from sqlalchemy.orm.scoping import scoped_session

from galaxy.datatypes.sniff import (
    convert_function,
    stream_url_to_file,
)
from galaxy.exceptions import ObjectAttributeInvalidException
from galaxy.files import ConfiguredFileSources
from galaxy.model import (
    Dataset,
    DatasetSource,
    History,
    HistoryDatasetAssociation,
    LibraryDatasetDatasetAssociation,
)
from galaxy.objectstore import (
    ObjectStore,
    ObjectStorePopulator,
)

log = logging.getLogger(__name__)


class TransientDatasetPaths(NamedTuple):
    external_filename: str
    external_extra_files_path: str


class TransientPathMapper:
    @abc.abstractmethod
    def transient_paths_for(self, old_dataset: Dataset) -> TransientDatasetPaths:
        """Map datset to transient paths for detached HDAs.

        Decide external_filename and external_extra_files_path that the supplied dataset's
        materialized dataset should have its files written to.
        """


class SimpleTransientPathMapper(TransientPathMapper):
    def __init__(self, staging_directory: str):
        self._staging_directory = staging_directory

    def transient_paths_for(self, old_dataset: Dataset) -> TransientDatasetPaths:
        external_filename_basename = "dataset_%s.dat" % str(old_dataset.uuid)
        external_filename = os.path.join(self._staging_directory, external_filename_basename)
        external_extras_basename = "dataset_%s_files" % str(old_dataset.uuid)
        external_extras = os.path.join(self._staging_directory, external_extras_basename)
        return TransientDatasetPaths(external_filename, external_extras)


class DatasetInstanceMaterializer:
    """This class is responsible for ensuring dataset instances are not deferred."""

    def __init__(
        self,
        attached: bool,
        object_store_populator: Optional[ObjectStorePopulator] = None,
        transient_path_mapper: Optional[TransientPathMapper] = None,
        file_sources: Optional[ConfiguredFileSources] = None,
        sa_session: Optional[scoped_session] = None,
    ):
        """Constructor for DatasetInstanceMaterializer.

        If attached is true, these objects should be created in a supplied object store.
        If not, this class produces transient HDAs with external_filename and
        external_extra_files_path set.
        """
        self._attached = attached
        self._transient_path_mapper = transient_path_mapper
        self._object_store_populator = object_store_populator
        self._file_sources = file_sources
        self._sa_session = sa_session

    def ensure_materialized(
        self,
        dataset_instance: Union[HistoryDatasetAssociation, LibraryDatasetDatasetAssociation],
        target_history: Optional[History] = None,
    ) -> HistoryDatasetAssociation:
        """Create a new detached dataset instance from the supplied instance.

        There will be times we want it usable as is without an objectstore and times
        we want to place it in an objectstore.
        """
        attached = self._attached
        dataset = dataset_instance.dataset
        if dataset.state != Dataset.states.DEFERRED and isinstance(dataset_instance, HistoryDatasetAssociation):
            return dataset_instance

        materialized_dataset = Dataset()
        materialized_dataset.state = Dataset.states.OK
        materialized_dataset.deleted = False
        materialized_dataset.purged = False
        materialized_dataset.sources = [s.copy() for s in dataset.sources]
        materialized_dataset.hashes = [h.copy() for h in dataset.hashes]

        target_source = self._find_closest_dataset_source(dataset)
        if attached:
            object_store_populator = self._object_store_populator
            assert object_store_populator
            object_store = object_store_populator.object_store
            store_by = object_store.get_store_by(dataset)
            if store_by == "id":
                # we need a flush...
                sa_session = self._sa_session
                if sa_session is None:
                    sa_session = object_session(dataset_instance)
                sa_session.add(materialized_dataset)
                sa_session.flush()
            object_store_populator.set_dataset_object_store_id(materialized_dataset)
            path = self._stream_source(target_source, datatype=dataset_instance.datatype)
            object_store.update_from_file(materialized_dataset, file_name=path)
        else:
            transient_path_mapper = self._transient_path_mapper
            assert transient_path_mapper
            transient_paths = transient_path_mapper.transient_paths_for(dataset)
            # TODO: optimize this by streaming right to this path...
            # TODO: take into acount transform and ensure we are and are not modifying the file as appropriate.
            path = self._stream_source(target_source, datatype=dataset_instance.datatype)
            shutil.move(path, transient_paths.external_filename)
            materialized_dataset.external_filename = transient_paths.external_filename

        history = target_history
        if history is None and isinstance(dataset_instance, HistoryDatasetAssociation):
            try:
                history = dataset_instance.history
            except DetachedInstanceError:
                history = None
        materialized_dataset_instance = HistoryDatasetAssociation(
            create_dataset=False,  # is the default but lets make this really clear...
            history=history,
        )
        materialized_dataset_instance.copy_from(
            dataset_instance, new_dataset=materialized_dataset, include_tags=attached
        )
        return materialized_dataset_instance

    def _stream_source(self, target_source: DatasetSource, datatype) -> str:
        path = stream_url_to_file(target_source.source_uri, file_sources=self._file_sources)
        transform = target_source.transform or []
        to_posix_lines = False
        spaces_to_tabs = False
        datatype_groom = False
        for transform_action in transform:
            action = transform_action["action"]
            if action == "to_posix_lines":
                to_posix_lines = True
            elif action == "spaces_to_tabs":
                spaces_to_tabs = True
            elif action == "datatype_groom":
                datatype_groom = True
            else:
                raise Exception(f"Failed to materialize dataest, unknown transformation action {action} applied.")
        if to_posix_lines or spaces_to_tabs:
            convert_fxn = convert_function(to_posix_lines, spaces_to_tabs)
            convert_result = convert_fxn(path, False)
            path = convert_result.converted_path
        if datatype_groom:
            datatype.groom_dataset_content(path)
        return path

    def _find_closest_dataset_source(self, dataset: Dataset) -> DatasetSource:
        best_source = None
        for source in dataset.sources:
            if source.extra_files_path:
                continue
            best_source = source
            break
        if best_source is None:
            # TODO: implement test case...
            raise ObjectAttributeInvalidException("dataset does not contain any valid dataset sources")
        return best_source


def materializer_factory(
    attached: bool,
    object_store: Optional[ObjectStore] = None,
    object_store_populator: Optional[ObjectStorePopulator] = None,
    transient_path_mapper: Optional[TransientPathMapper] = None,
    transient_directory: Optional[str] = None,
    file_sources: Optional[ConfiguredFileSources] = None,
    sa_session: Optional[scoped_session] = None,
) -> DatasetInstanceMaterializer:
    if object_store_populator is None and object_store is not None:
        object_store_populator = ObjectStorePopulator(object_store, None)
    if transient_path_mapper is None and transient_directory is not None:
        transient_path_mapper = SimpleTransientPathMapper(transient_directory)
    return DatasetInstanceMaterializer(
        attached,
        object_store_populator=object_store_populator,
        transient_path_mapper=transient_path_mapper,
        file_sources=file_sources,
        sa_session=sa_session,
    )
