"""Unit tests for the path rewrites of ``PulsarComputeEnvironment``.

Staging (``transfer``/``copy``) and ``none`` are covered end to end by the
composite tools in ``test/integration/test_pulsar_embedded.py`` and
``test/integration/test_pulsar_embedded_none_local_metadata.py``. These tests
cover the ``rewrite`` file action, which no integration test exercises.
"""

from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Optional,
)

from galaxy.jobs.runners.pulsar import PulsarComputeEnvironment

LOCAL_FILES = "/galaxy/files"
LOCAL_WORKING_DIRECTORY = "/galaxy/jobs/1"
REMOTE_JOB_DIRECTORY = "/pulsar/1"


@dataclass
class FakeDataset:
    name: str

    @property
    def extra_files_path(self) -> str:
        return f"{LOCAL_FILES}/{self.name}_files"

    def get_file_name(self) -> str:
        return f"{LOCAL_FILES}/{self.name}.dat"


class FakeLocalComputeEnvironment:
    """Galaxy's own compute environment: datasets are read and written in place."""

    def input_path_rewrite(self, dataset: FakeDataset) -> str:
        return dataset.get_file_name()

    def output_path_rewrite(self, dataset: FakeDataset) -> str:
        return dataset.get_file_name()

    def working_directory(self) -> str:
        return LOCAL_WORKING_DIRECTORY

    def version_path(self) -> str:
        return f"{LOCAL_WORKING_DIRECTORY}/COMMAND_VERSION"


class FakeJobWrapper:
    def default_compute_environment(self) -> FakeLocalComputeEnvironment:
        return FakeLocalComputeEnvironment()


@dataclass
class FakePulsarClient:
    """The client attributes Pulsar's ``FileActionMapper`` reads."""

    default_file_action: str
    file_actions: dict[str, Any] = field(default_factory=dict)
    action_config_path: Optional[str] = None
    files_endpoint: Optional[str] = None


REMOTE_JOB_CONFIG = {
    "inputs_directory": f"{REMOTE_JOB_DIRECTORY}/inputs",
    "outputs_directory": f"{REMOTE_JOB_DIRECTORY}/outputs",
    "working_directory": f"{REMOTE_JOB_DIRECTORY}/working",
    "unstructured_files_directory": f"{REMOTE_JOB_DIRECTORY}/unstructured",
    "configs_directory": f"{REMOTE_JOB_DIRECTORY}/configs",
    "tools_directory": f"{REMOTE_JOB_DIRECTORY}/tools",
    "system_properties": {"separator": "/"},
}


def _rewrite_compute_environment(destination_directory: str) -> PulsarComputeEnvironment:
    """Pulsar sees Galaxy's files at ``destination_directory`` without staging them."""
    file_actions = {
        "paths": [
            {
                "path": LOCAL_FILES,
                "action": "rewrite",
                "source_directory": LOCAL_FILES,
                "destination_directory": destination_directory,
            }
        ]
    }
    pulsar_client = FakePulsarClient(default_file_action="transfer", file_actions=file_actions)
    return PulsarComputeEnvironment(pulsar_client, FakeJobWrapper(), REMOTE_JOB_CONFIG)


def test_rewrite_action_rewrites_extra_files_beside_dataset():
    compute_environment = _rewrite_compute_environment("/mnt/files")
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) == "/mnt/files/dataset_1.dat"
    assert compute_environment.input_extra_files_rewrite(dataset) == "/mnt/files/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/mnt/files/dataset_1_files"
    assert compute_environment.path_rewrites_input_extra == {
        "/galaxy/files/dataset_1_files": "/mnt/files/dataset_1_files"
    }


def test_unchanged_rewrite_action_leaves_extra_files_in_place():
    compute_environment = _rewrite_compute_environment(LOCAL_FILES)
    dataset = FakeDataset("dataset_1")

    assert compute_environment.input_path_rewrite(dataset) is None
    assert compute_environment.input_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    assert compute_environment.output_extra_files_rewrite(dataset) == "/galaxy/files/dataset_1_files"
    # Nothing to stage.
    assert compute_environment.path_rewrites_input_extra == {}
