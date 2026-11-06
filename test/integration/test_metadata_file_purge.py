from galaxy import model
from galaxy_test.base.populators import (
    DatasetPopulator,
    LibraryPopulator,
)
from galaxy_test.driver import integration_util
from ._metadata_files import UsesMetadataFiles

PURGED_AND_GONE = {"deleted": True, "purged": True, "exists": False}


class TestMetadataFilePurge(integration_util.IntegrationTestCase, UsesMetadataFiles):
    dataset_populator: DatasetPopulator
    library_populator: LibraryPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.library_populator = LibraryPopulator(self.galaxy_interactor)

    def _hda(self, encoded_id: str) -> model.HistoryDatasetAssociation:
        hda = self._app.model.session.get(model.HistoryDatasetAssociation, self._app.security.decode_id(encoded_id))
        assert hda is not None
        return hda

    def _library_dataset(self, encoded_id: str) -> model.LibraryDataset:
        self._app.model.session.rollback()
        library_dataset = self._app.model.session.get(model.LibraryDataset, self._app.security.decode_id(encoded_id))
        assert library_dataset is not None
        return library_dataset

    def _purge_library_dataset(self, library_id: str, library_dataset_id: str) -> None:
        response = self._delete(
            f"libraries/{library_id}/contents/{library_dataset_id}", data={"purge": True}, json=True
        )
        self._assert_status_code_is(response, 200)

    def test_purge_hda(self):
        history_id = self.dataset_populator.new_history()
        dataset = self.dataset_populator.new_dataset(history_id, content="ABC", wait=True)
        metadata_file = self._add_metadata_file(self._hda(dataset["id"]))

        self.dataset_populator.delete_dataset(history_id, dataset["id"], purge=True, wait_for_purge=True)

        assert self._metadata_file_state(*metadata_file) == PURGED_AND_GONE

    def test_purge_library_item(self):
        library, library_dataset = self.library_populator.new_library_dataset_in_private_library("metadata_files")
        metadata_file = self._add_metadata_file(
            self._library_dataset(library_dataset["id"]).library_dataset_dataset_association
        )

        self._purge_library_dataset(library["id"], library_dataset["id"])

        assert self._metadata_file_state(*metadata_file) == PURGED_AND_GONE
