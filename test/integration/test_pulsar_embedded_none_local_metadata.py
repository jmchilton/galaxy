"""Integration tests for the Pulsar embedded runner with default_file_action: none
and metadata set by Galaxy (remote_metadata: false).

This is the usual shared filesystem setup (Pulsar reads and writes Galaxy's
files in place). These tools ask for extra files paths, see
https://github.com/galaxyproject/galaxy/issues/24600
"""

import os

from galaxy_test.driver import integration_util

SCRIPT_DIRECTORY = os.path.abspath(os.path.dirname(__file__))
EMBEDDED_PULSAR_JOB_CONFIG_FILE = os.path.join(SCRIPT_DIRECTORY, "embedded_pulsar_none_local_metadata_job_conf.yml")


class EmbeddedNoneLocalMetadataPulsarIntegrationInstance(integration_util.IntegrationInstance):
    """Describe a Galaxy test instance with embedded pulsar configured with default_file_action: none."""

    framework_tool_and_types = True

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        config["job_config_file"] = EMBEDDED_PULSAR_JOB_CONFIG_FILE
        config["object_store_store_by"] = "uuid"
        config["retry_metadata_internally"] = False


instance = integration_util.integration_module_instance(EmbeddedNoneLocalMetadataPulsarIntegrationInstance)

test_tools = integration_util.integration_tool_runner(
    [
        # $input.extra_files_path
        "composite",
        # $input.extra_files_path, $output.files_path and $output.extra_files_path
        "composite_output_tests",
    ]
)
