from galaxy_test.api.test_histories import ImportExportTests
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
