from types import SimpleNamespace
from typing import (
    cast,
    TYPE_CHECKING,
)

import pytest

from galaxy.jobs.runners import BaseJobRunner
from galaxy.tool_util.deps.image_references import ContainerAllowlist
from galaxy.tool_util.deps.requirements import ContainerDescription

if TYPE_CHECKING:
    from galaxy.app import GalaxyManagerApplication
    from galaxy.jobs import MinimalJobWrapper

RESOLVED = object()


def _job_wrapper(identifier: str):
    tool = SimpleNamespace(
        tool_type="user_defined",
        containers=[ContainerDescription(identifier)],
        requirements=[],
        requires_galaxy_python_environment=False,
        docker_env_pass_through=[],
        id="cat",
        version="1.0",
        profile=24.0,
        tool_dir="/tools/cat",
    )
    job_wrapper = SimpleNamespace(
        tool=tool,
        guest_ports=None,
        working_directory="/jobs/000/1",
        tool_working_directory="/jobs/000/1/working",
        tmp_directory=lambda: None,
        home_directory=lambda: None,
        job_destination=SimpleNamespace(params={}, tool_env_names=[]),
        set_container=lambda container: None,
    )
    return cast("MinimalJobWrapper", job_wrapper)


def _runner():
    runner = BaseJobRunner.__new__(BaseJobRunner)
    runner.app = cast(
        "GalaxyManagerApplication",
        SimpleNamespace(
            # Resolvers may map the declared image to anything, e.g. a cached Singularity image path.
            container_finder=SimpleNamespace(find_container=lambda *args: RESOLVED),
            dynamic_tool_manager=SimpleNamespace(container_allowlist=ContainerAllowlist(["quay.io/biocontainers/*"])),
            object_store=None,
        ),
    )
    return runner


@pytest.fixture(autouse=True)
def no_disk_paths(monkeypatch):
    monkeypatch.setattr("galaxy.jobs.runners.get_disk_paths", lambda object_store: set())


def test_allowed_declared_container_passes_whatever_the_resolver_returns():
    assert _runner()._find_container(_job_wrapper("quay.io/biocontainers/samtools:1.17")) is RESOLVED
