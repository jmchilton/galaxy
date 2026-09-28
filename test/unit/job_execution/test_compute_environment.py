import json
from types import SimpleNamespace
from unittest.mock import Mock

from galaxy.job_execution.compute_environment import RemoteComputeEnvironment, serialize_compute_environment
from galaxy.model import Dataset, MetadataFile


def test_remote_environment_uses_runner_paths_without_object_store_access():
    metadata = Mock(spec=MetadataFile)
    metadata.get_file_name.return_value = "/galaxy/metadata/index.bai"
    ordinary = SimpleNamespace(
        dataset=SimpleNamespace(uuid="input-uuid"),
        state=Dataset.states.OK,
        states=Dataset.states,
        metadata={"bam_index": metadata},
        extra_files_path_exists=lambda: True,
    )
    deferred = SimpleNamespace(
        dataset=SimpleNamespace(uuid="deferred-uuid"), state=Dataset.states.DEFERRED, states=Dataset.states
    )
    plain = SimpleNamespace(
        dataset=SimpleNamespace(uuid="plain-uuid"),
        state=Dataset.states.OK,
        states=Dataset.states,
        metadata={},
        extra_files_path_exists=lambda: False,
    )
    output = SimpleNamespace(dataset=SimpleNamespace(uuid="output-uuid"))
    job_io = Mock()
    job_io.get_input_datasets.return_value = [ordinary, deferred, plain]
    job_io.output_hdas_and_paths = {"out": (output, None)}
    runner = Mock()
    runner.input_path_rewrite.return_value = "/pulsar/inputs/input.dat"
    runner.output_path_rewrite.return_value = "/pulsar/outputs/output.dat"
    runner.input_extra_files_rewrite.return_value = "/pulsar/inputs/composite"
    runner.output_extra_files_rewrite.return_value = "/pulsar/outputs/composite"
    runner.input_metadata_rewrite.return_value = "/pulsar/inputs/index.bai"
    for name in (
        "working_directory",
        "config_directory",
        "env_config_directory",
        "new_file_path",
        "tool_directory",
        "version_path",
        "home_directory",
        "tmp_directory",
        "galaxy_url",
    ):
        getattr(runner, name).return_value = f"/pulsar/{name}"

    snapshot = json.loads(json.dumps(serialize_compute_environment(runner, job_io)))
    # Execution-side JobIO has no accessible Galaxy object store.
    remote_io = Mock()
    remote_io.get_input_path.side_effect = AssertionError("Galaxy input path queried")
    remote_io.get_output_path.side_effect = AssertionError("Galaxy output path queried")
    remote = RemoteComputeEnvironment(remote_io, Mock(), snapshot)
    assert remote.input_path_rewrite(ordinary) == "/pulsar/inputs/input.dat"
    assert remote.output_path_rewrite(output) == "/pulsar/outputs/output.dat"
    assert remote.input_extra_files_rewrite(ordinary) == "/pulsar/inputs/composite"
    assert remote.output_extra_files_rewrite(output) == "/pulsar/outputs/composite"
    assert remote.input_metadata_rewrite(ordinary, "/galaxy/metadata/index.bai") == "/pulsar/inputs/index.bai"
    assert remote.working_directory() == "/pulsar/working_directory"
    assert remote.output_names() == ["output.dat"]
    assert "deferred-uuid" not in snapshot["paths"]["inputs"]
    assert runner.input_path_rewrite.call_count == 2
    # Registering a missing extra-files directory would make Pulsar try to stage it.
    runner.input_extra_files_rewrite.assert_called_once_with(ordinary)
    assert remote.input_extra_files_rewrite(plain) == "/pulsar/inputs/input_files"

    # A deferred input materialized remotely has a path supplied by its new dataset.
    remote_io.get_input_path.side_effect = None
    remote_io.get_input_path.return_value = "/pulsar/inputs/materialized.dat"
    assert remote.input_path_rewrite(deferred) == "/pulsar/inputs/materialized.dat"
    assert remote.input_extra_files_rewrite(deferred) == "/pulsar/inputs/materialized_files"
