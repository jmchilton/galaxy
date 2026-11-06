from galaxy import model
from galaxy_test.base.populators import (
    DatasetPopulator,
    LibraryPopulator,
)
from galaxy_test.driver import integration_util
from ._metadata_files import (
    METADATA_FILE_CONTENT,
    UsesMetadataFiles,
)

PURGED_AND_GONE = {"deleted": True, "purged": True, "exists": False}


class MetadataFilePurgeTestCase(integration_util.IntegrationTestCase, UsesMetadataFiles):
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

    def _copy_to_library(self, library: dict, hda_id: str) -> str:
        response = self._post(
            f"libraries/{library['id']}/contents",
            data={"folder_id": library["root_folder_id"], "create_type": "file", "from_hda_id": hda_id},
            json=True,
        )
        self._assert_status_code_is(response, 200)
        return response.json()["library_dataset_id"]


class TestMetadataFilePurge(MetadataFilePurgeTestCase):
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

    def test_purge_hda_keeps_file_named_by_row_of_live_dataset(self):
        history_id = self.dataset_populator.new_history()
        live = self.dataset_populator.new_dataset(history_id, content="live", wait=True)
        purged = self.dataset_populator.new_dataset(history_id, content="purged", wait=True)
        live_file = self._add_metadata_file(self._hda(live["id"]))
        purged_file = self._add_metadata_file(self._hda(purged["id"]), uuid=self._metadata_file_uuid(live_file[0]))
        assert live_file[1] == purged_file[1]

        self.dataset_populator.delete_dataset(history_id, purged["id"], purge=True, wait_for_purge=True)

        assert self._metadata_file_state(*purged_file) == {"deleted": True, "purged": True, "exists": True}
        assert self._metadata_file_state(*live_file) == {"deleted": False, "purged": False, "exists": True}
        with open(live_file[1], "rb") as f:
            assert f.read() == METADATA_FILE_CONTENT

        # the last row naming the file releases it
        self.dataset_populator.delete_dataset(history_id, live["id"], purge=True, wait_for_purge=True)
        assert self._metadata_file_state(*live_file) == PURGED_AND_GONE

    def test_purge_library_item_with_live_hda_copy(self):
        history_id = self.dataset_populator.new_history()
        bam = self.dataset_populator.new_bam_dataset(history_id, self.test_data_resolver)
        self.dataset_populator.wait_for_history(history_id, assert_ok=True)
        library = self.library_populator.new_private_library("metadata_files_live_hda")
        library_dataset_id = self._copy_to_library(library, bam["id"])
        ldda = self._library_dataset(library_dataset_id).library_dataset_dataset_association
        hda = self._hda(bam["id"])
        assert ldda.dataset_id == hda.dataset_id
        ldda_index = ldda.metadata.bam_index
        hda_index = hda.metadata.bam_index
        assert ldda_index.id != hda_index.id
        ldda_file = ldda_index.id, ldda_index.get_file_name()
        hda_file = hda_index.id, hda_index.get_file_name()
        with open(hda_file[1], "rb") as f:
            hda_index_content = f.read()
        assert hda_index_content

        self._purge_library_dataset(library["id"], library_dataset_id)

        assert self._metadata_file_state(*ldda_file) == PURGED_AND_GONE
        assert self._metadata_file_state(*hda_file) == {"deleted": False, "purged": False, "exists": True}
        with open(hda_file[1], "rb") as f:
            assert f.read() == hda_index_content
        details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=bam["id"])
        assert details["purged"] is False

    def test_purge_library_item_removes_files_of_all_versions(self):
        library, library_dataset = self.library_populator.new_library_dataset_in_private_library("metadata_versions")
        sa_session = self._app.model.session
        library_dataset_model = self._library_dataset(library_dataset["id"])
        current = library_dataset_model.library_dataset_dataset_association
        older = model.LibraryDatasetDatasetAssociation(
            name="older",
            extension="txt",
            library_dataset=library_dataset_model,
            create_dataset=True,
            sa_session=sa_session,
        )
        sa_session.add(older)
        sa_session.commit()
        older_file = self._add_metadata_file(older)
        current_file = self._add_metadata_file(current)

        self._purge_library_dataset(library["id"], library_dataset["id"])

        assert self._metadata_file_state(*older_file) == PURGED_AND_GONE
        assert self._metadata_file_state(*current_file) == PURGED_AND_GONE


class TestMetadataFilePurgeStoreById(MetadataFilePurgeTestCase):
    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["object_store_store_by"] = "id"

    def test_purge_hda_removes_own_file_despite_shared_uuid(self):
        history_id = self.dataset_populator.new_history()
        live = self.dataset_populator.new_dataset(history_id, content="live", wait=True)
        purged = self.dataset_populator.new_dataset(history_id, content="purged", wait=True)
        live_file = self._add_metadata_file(self._hda(live["id"]))
        purged_file = self._add_metadata_file(self._hda(purged["id"]), uuid=self._metadata_file_uuid(live_file[0]))
        assert live_file[1] != purged_file[1]

        self.dataset_populator.delete_dataset(history_id, purged["id"], purge=True, wait_for_purge=True)

        assert self._metadata_file_state(*purged_file) == PURGED_AND_GONE
        assert self._metadata_file_state(*live_file) == {"deleted": False, "purged": False, "exists": True}
