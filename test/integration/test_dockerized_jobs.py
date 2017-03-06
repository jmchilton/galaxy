"""Integration tests for running tools in Docker containers."""

import os

from base import integration_util
from base.populators import (
    DatasetPopulator,
)

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
DOCKERIZED_JOB_CONFIG_FILE = os.path.join(SCRIPT_DIRECTORY, "dockerized_job_conf.xml")
# DOCKERIZED_JOB_DEPENDENCY_RESOLVERS_CONF = os.path.join(SCRIPT_DIRECTORY, "dockerzied_dependency_resolvers_conf.xml")


class DockerizedJobsIntegrationTestCase(integration_util.IntegrationTestCase):

    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        config["job_config_file"] = DOCKERIZED_JOB_CONFIG_FILE
        # Disable tool dependency resolution.
        config["tool_dependency_dir"] = "none"
        config["enable_beta_mulled_containers"] = "true"
        config["strict_cwl_validation"] = "false"

    def setUp(self):
        super(DockerizedJobsIntegrationTestCase, self).setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.history_id = self.dataset_populator.new_history()

    def test_explicit(self):
        self.dataset_populator.run_tool("mulled_example_explicit", {}, self.history_id)
        self.dataset_populator.wait_for_history(self.history_id, assert_ok=True)
        output = self.dataset_populator.get_history_dataset_content(self.history_id)
        assert "0.7.15-r1140" in output

    def test_mulled_simple(self):
        self.dataset_populator.run_tool("mulled_example_simple", {}, self.history_id)
        self.dataset_populator.wait_for_history(self.history_id, assert_ok=True)
        output = self.dataset_populator.get_history_dataset_content(self.history_id)
        assert "0.7.15-r1140" in output

    def test_cwl(self):
        run_object = self.dataset_populator.run_cwl_tool("md5sum_non_strict", "test/functional/tools/cwl_tools/v1.0_custom/md5sum_job.json")
        output_file = run_object.output(0)
        output_content = self.dataset_populator.get_history_dataset_content( run_object.history_id, dataset=output_file )
        self.assertEquals(output_content, "00579a00e3e7fa0674428ac7049423e2\n")
