from galaxy.model.unittest_utils.store_fixtures import (
    deferred_hda_model_store_dict,
    one_ld_library_deferred_model_store_dict,
    TEST_LIBRARY_NAME,
)
from galaxy_test.base.populators import (
    DatasetPopulator,
    LibraryPopulator,
    uses_test_history,
)
from galaxy_test.driver.integration_util import (
    IntegrationTestCase,
    setup_celery_includes,
    UsesCeleryTasks,
)


celery_includes = setup_celery_includes()


class MaterializeDatasetInstanceTasaksIntegrationTestCase(IntegrationTestCase, UsesCeleryTasks):

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        cls.setup_celery_config(config)

    def setUp(self):
        super().setUp()
        self.library_populator = LibraryPopulator(self.galaxy_interactor)
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    @uses_test_history(require_new=True)
    def test_materialize_history_dataset(self, history_id):
        as_list = self.dataset_populator.create_contents_from_store(
            history_id,
            store_dict=deferred_hda_model_store_dict(),
        )
        assert len(as_list) == 1
        deferred_hda = as_list[0]
        assert deferred_hda["model_class"] == "HistoryDatasetAssociation"
        assert deferred_hda["state"] == "deferred"
        assert not deferred_hda["deleted"]
        materialize_payload = dict(
            source='hda',
            content=deferred_hda["id"],
        )

        create_response = self._post(f"histories/{history_id}/materialize", materialize_payload)
        create_response.raise_for_status()
        assert "id" in create_response.json()
        self.dataset_populator.wait_on_history_length(history_id, 2)
        new_hda_details = self.dataset_populator.get_history_dataset_details(history_id, hid=2, assert_ok=False, wait=False)
        assert new_hda_details["model_class"] == "HistoryDatasetAssociation"
        assert new_hda_details["state"] == "ok"
        assert not new_hda_details["deleted"]

    @uses_test_history(require_new=True)
    def test_materialize_library_dataset(self, history_id):
        response = self.library_populator.create_from_store(store_dict=one_ld_library_deferred_model_store_dict())
        assert isinstance(response, list)
        assert len(response) == 1
        library_summary = response[0]
        assert library_summary["name"] == TEST_LIBRARY_NAME
        assert "id" in library_summary
        ld = self.library_populator.get_library_contents_with_path(library_summary["id"], "/my cool name")
        assert ld
        materialize_payload = dict(
            source='ldda',
            content=ld["id"],
        )
        create_response = self._post(f"histories/{history_id}/materialize", materialize_payload)
        create_response.raise_for_status()
        assert "id" in create_response.json()

        self.dataset_populator.wait_on_history_length(history_id, 1)
        new_hda_details = self.dataset_populator.get_history_dataset_details(history_id, hid=1, assert_ok=False, wait=False)
        assert new_hda_details["model_class"] == "HistoryDatasetAssociation"
        assert new_hda_details["state"] == "ok"
        assert not new_hda_details["deleted"]
