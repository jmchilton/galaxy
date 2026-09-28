import os
from abc import (
    ABCMeta,
    abstractmethod,
)
from typing import (
    Any,
)

from galaxy.job_execution.datasets import DeferrableObjectsT
from galaxy.job_execution.setup import JobIO
from galaxy.model import Job, MetadataFile


def dataset_path_to_extra_path(path: str) -> str:
    base_path = path[0 : -len(".dat")]
    return f"{base_path}_files"


class ComputeEnvironment(metaclass=ABCMeta):
    """Definition of the job as it will be run on the (potentially) remote
    compute server.
    """

    def __init__(self):
        self.materialized_objects: dict[str, DeferrableObjectsT] = {}

    @abstractmethod
    def output_names(self):
        """Output unqualified filenames defined by job."""

    @abstractmethod
    def input_path_rewrite(self, dataset):
        """Input path for specified dataset."""

    @abstractmethod
    def output_path_rewrite(self, dataset):
        """Output path for specified dataset."""

    @abstractmethod
    def input_extra_files_rewrite(self, dataset):
        """Input extra files path rewrite for specified dataset."""

    @abstractmethod
    def output_extra_files_rewrite(self, dataset):
        """Output extra files path rewrite for specified dataset."""

    @abstractmethod
    def input_metadata_rewrite(self, dataset, metadata_value):
        """Input metadata path rewrite for specified dataset."""

    @abstractmethod
    def unstructured_path_rewrite(self, path):
        """Rewrite loc file paths, etc.."""

    @abstractmethod
    def working_directory(self):
        """Job working directory (potentially remote)"""

    @abstractmethod
    def config_directory(self):
        """Directory containing config files (potentially remote)"""

    @abstractmethod
    def env_config_directory(self):
        """Working directory (possibly as environment variable evaluation)."""

    @abstractmethod
    def sep(self):
        """os.path.sep for the platform this job will execute in."""

    @abstractmethod
    def new_file_path(self):
        """Absolute path to dump new files for this job on compute server."""

    @abstractmethod
    def tool_directory(self):
        """Absolute path to tool files for this job on compute server."""

    @abstractmethod
    def version_path(self):
        """Location of the version file for the underlying tool."""

    @abstractmethod
    def home_directory(self):
        """Home directory of target job - none if HOME should not be set."""

    @abstractmethod
    def tmp_directory(self):
        """Temp directory of target job - none if HOME should not be set."""

    @abstractmethod
    def galaxy_url(self):
        """URL to access Galaxy API from for this compute environment."""

    @abstractmethod
    def get_file_sources_dict(self) -> dict[str, Any]:
        """Return file sources dict for current user."""


class SimpleComputeEnvironment:
    def config_directory(self):
        return os.path.join(self.working_directory(), "configs")  # type: ignore[attr-defined]

    def sep(self):
        return os.path.sep


class SharedComputeEnvironment(SimpleComputeEnvironment, ComputeEnvironment):
    """Default ComputeEnvironment for job and task wrapper to pass
    to ToolEvaluator - valid when Galaxy and compute share all the relevant
    file systems.
    """

    job_id: JobIO
    job: Job

    def __init__(self, job_io: JobIO, job: Job):
        self.job_io = job_io
        self.job = job

    def get_file_sources_dict(self) -> dict[str, Any]:
        return self.job_io.file_sources_dict

    def output_names(self):
        return self.job_io.get_output_basenames()

    def output_paths(self):
        return self.job_io.get_output_fnames()

    def input_path_rewrite(self, dataset):
        return str(self.job_io.get_input_path(dataset))

    def output_path_rewrite(self, dataset):
        return str(self.job_io.get_output_path(dataset))

    def input_extra_files_rewrite(self, dataset):
        input_path_rewrite = self.input_path_rewrite(dataset)
        return dataset_path_to_extra_path(input_path_rewrite)

    def output_extra_files_rewrite(self, dataset):
        output_path_rewrite = self.output_path_rewrite(dataset)
        return dataset_path_to_extra_path(output_path_rewrite)

    def input_metadata_rewrite(self, dataset, metadata_value):
        return None

    def unstructured_path_rewrite(self, path):
        return None

    def working_directory(self):
        return self.job_io.working_directory

    def env_config_directory(self):
        """Working directory (possibly as environment variable evaluation)."""
        return "$_GALAXY_JOB_DIR"

    def new_file_path(self):
        return self.job_io.new_file_path

    def version_path(self):
        return self.job_io.version_path

    def tool_directory(self):
        return self.job_io.tool_directory

    def home_directory(self):
        return self.job_io.home_directory

    def tmp_directory(self):
        return self.job_io.tmp_directory

    def galaxy_url(self):
        return self.job_io.galaxy_url


def serialize_compute_environment(compute_environment: ComputeEnvironment, job_io: JobIO) -> dict[str, Any]:
    """Capture runner-resolved paths before exporting the job for remote evaluation."""
    paths: dict[str, dict[str, str]] = {
        "inputs": {},
        "outputs": {},
        "input_extra_files": {},
        "output_extra_files": {},
        "metadata": {},
    }
    for dataset in job_io.get_input_datasets():
        if dataset.state == dataset.states.DEFERRED:
            # Materialization on the execution host supplies its own paths.
            continue
        paths["inputs"][str(dataset.dataset.uuid)] = (
            compute_environment.input_path_rewrite(dataset) or dataset.get_file_name()
        )
        if dataset.extra_files_path_exists():
            paths["input_extra_files"][str(dataset.dataset.uuid)] = (
                compute_environment.input_extra_files_rewrite(dataset) or dataset.extra_files_path
            )
        else:
            paths["input_extra_files"][str(dataset.dataset.uuid)] = dataset_path_to_extra_path(
                paths["inputs"][str(dataset.dataset.uuid)]
            )
        for value in dataset.metadata.values():
            if isinstance(value, MetadataFile):
                filename = value.get_file_name()
                paths["metadata"][filename] = compute_environment.input_metadata_rewrite(dataset, filename) or filename
    for dataset, _ in job_io.output_hdas_and_paths.values():
        paths["outputs"][str(dataset.dataset.uuid)] = (
            compute_environment.output_path_rewrite(dataset) or dataset.get_file_name()
        )
        paths["output_extra_files"][str(dataset.dataset.uuid)] = (
            compute_environment.output_extra_files_rewrite(dataset) or dataset.extra_files_path
        )
    directories = {
        name: getattr(compute_environment, name)()
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
        )
    }
    return {"paths": paths, "directories": directories}


class RemoteComputeEnvironment(SharedComputeEnvironment):
    """Use paths resolved by the runner instead of querying Galaxy's object store."""

    def __init__(self, job_io: JobIO, job: Job, environment: dict[str, Any]):
        super().__init__(job_io, job)
        self.paths = environment["paths"]
        self.directories = environment["directories"]

    def input_path_rewrite(self, dataset):
        path = self.paths["inputs"].get(str(dataset.dataset.uuid))
        return path if path is not None else super().input_path_rewrite(dataset)

    def output_path_rewrite(self, dataset):
        return self.paths["outputs"][str(dataset.dataset.uuid)]

    def input_extra_files_rewrite(self, dataset):
        path = self.paths["input_extra_files"].get(str(dataset.dataset.uuid))
        return path if path is not None else super().input_extra_files_rewrite(dataset)

    def output_extra_files_rewrite(self, dataset):
        return self.paths["output_extra_files"][str(dataset.dataset.uuid)]

    def input_metadata_rewrite(self, dataset, metadata_value):
        return self.paths["metadata"].get(metadata_value)

    def output_names(self):
        return [os.path.basename(path) for path in self.paths["outputs"].values()]

    def working_directory(self):
        return self.directories["working_directory"]

    def config_directory(self):
        return self.directories["config_directory"]

    def env_config_directory(self):
        return self.directories["env_config_directory"]

    def new_file_path(self):
        return self.directories["new_file_path"]

    def tool_directory(self):
        return self.directories["tool_directory"]

    def version_path(self):
        return self.directories["version_path"]

    def home_directory(self):
        return self.directories["home_directory"]

    def tmp_directory(self):
        return self.directories["tmp_directory"]

    def galaxy_url(self):
        return self.directories["galaxy_url"]
