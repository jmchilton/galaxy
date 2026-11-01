"""Unit tests for the path rewrites of ``PulsarComputeEnvironment``."""

from types import SimpleNamespace
from typing import (
    Any,
    Optional,
)

from galaxy.jobs.runners.pulsar import PulsarComputeEnvironment

LOCAL_FILES = "/galaxy/files"
LOCAL_WORKING_DIRECTORY = "/galaxy/jobs/1"
REMOTE_JOB_DIRECTORY = "/pulsar/1"


class FakeDataset:
    def __init__(self, name: str):
        self.file_name = f"{LOCAL_FILES}/{name}.dat"
        self.extra_files_path = f"{LOCAL_FILES}/{name}_files"

    def get_file_name(self) -> str:
        return self.file_name


class FakeLocalComputeEnvironment:
    def input_path_rewrite(self, dataset):
        return None

    def output_path_rewrite(self, dataset):
        return None

    def working_directory(self):
        return LOCAL_WORKING_DIRECTORY

    def version_path(self):
        return f"{LOCAL_WORKING_DIRECTORY}/COMMAND_VERSION"


def _compute_environment(default_file_action: str, file_actions: Optional[dict[str, Any]] = None):
    pulsar_client = SimpleNamespace(
        action_config_path=None,
        file_actions=file_actions or {},
        default_file_action=default_file_action,
        files_endpoint=None,
    )
    job_wrapper = SimpleNamespace(default_compute_environment=lambda: FakeLocalComputeEnvironment())
    remote_job_config = {
        "inputs_directory": f"{REMOTE_JOB_DIRECTORY}/inputs",
        "outputs_directory": f"{REMOTE_JOB_DIRECTORY}/outputs",
        "working_directory": f"{REMOTE_JOB_DIRECTORY}/working",
        "unstructured_files_directory": f"{REMOTE_JOB_DIRECTORY}/unstructured",
        "configs_directory": f"{REMOTE_JOB_DIRECTORY}/configs",
        "tools_directory": f"{REMOTE_JOB_DIRECTORY}/tools",
        "system_properties": {"separator": "/"},
    }
    return PulsarComputeEnvironment(pulsar_client, job_wrapper, remote_job_config)


def test_transfer_rewrites_extra_files_into_job_directory():
    compute_environment = _compute_environment("transfer")
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) == "/pulsar/1/inputs/dataset_1.dat"
    assert compute_environment.input_extra_files_rewrite(dataset) == "/pulsar/1/inputs/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/pulsar/1/outputs/dataset_1_files"
    # Input extra files are recorded so the client stages them.
    assert compute_environment.path_rewrites_input_extra == {
        "/galaxy/files/dataset_1_files": "/pulsar/1/inputs/dataset_1_files"
    }


def test_rewrite_action_rewrites_extra_files_beside_dataset():
    file_actions = {
        "paths": [
            {
                "path": LOCAL_FILES,
                "action": "rewrite",
                "source_directory": LOCAL_FILES,
                "destination_directory": "/mnt/files",
            }
        ]
    }
    compute_environment = _compute_environment("transfer", file_actions)
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) == "/mnt/files/dataset_1.dat"
    assert compute_environment.input_extra_files_rewrite(dataset) == "/mnt/files/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/mnt/files/dataset_1_files"
    assert compute_environment.path_rewrites_input_extra == {
        "/galaxy/files/dataset_1_files": "/mnt/files/dataset_1_files"
    }


def test_none_action_leaves_extra_files_in_place():
    compute_environment = _compute_environment("none")
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) is None
    assert compute_environment.input_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    # Nothing to stage.
    assert compute_environment.path_rewrites_input_extra == {}


def test_unchanged_rewrite_action_leaves_extra_files_in_place():
    file_actions = {
        "paths": [
            {
                "path": LOCAL_FILES,
                "action": "rewrite",
                "source_directory": LOCAL_FILES,
                "destination_directory": LOCAL_FILES,
            }
        ]
    }
    compute_environment = _compute_environment("transfer", file_actions)
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) is None
    assert compute_environment.input_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    assert compute_environment.path_rewrites_input_extra == {}
