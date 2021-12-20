from galaxy.model.unittest_utils.store_fixtures import (
    history_model_store_dict,
)
from galaxy_test.api.test_histories import ImportExportTests
from galaxy_test.base.api_asserts import (
    assert_has_keys,
)
from galaxy_test.driver.integration_util import (
    IntegrationTestCase,
    setup_celery_includes,
    UsesCeleryTasks,
)


celery_includes = setup_celery_includes()


class ImportExportHistoryOutputsToWorkingDirIntegrationTestCase(ImportExportTests, IntegrationTestCase):
    task_based = False
    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        config["outputs_to_working_directory"] = True
        config["metadata_strategy"] = "extended"

    def setUp(self):
        super().setUp()
        self._set_up_populators()


class ImportExportHistoryViaTasksIntegrationTestCase(ImportExportTests, IntegrationTestCase, UsesCeleryTasks):
    task_based = True
    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        cls.setup_celery_config(config)

    def setUp(self):
        super().setUp()
        self._set_up_populators()

    def test_import_from_model_store_async(self):
        async_history_name = "Model store imported history"
        store_dict = history_model_store_dict()
        store_dict["history"]["name"] = async_history_name
        response = self.dataset_populator.create_from_store_async(store_dict=store_dict)
        assert_has_keys(response, "id")
        self.dataset_populator.wait_for_history_with_name(
            async_history_name,
            "task based import history",
        )
