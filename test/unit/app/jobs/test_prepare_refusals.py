from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    cast,
)

import pytest

from galaxy import model
from galaxy.exceptions import InsufficientPermissionsException
from galaxy.jobs.runners import BaseJobRunner
from galaxy.tools.security_refusal import ToolInputRejected


@dataclass
class RefusingJobWrapper:
    """A queued job whose preparation refuses it."""

    refusal: Exception
    job_destination: Any = None
    failures: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def get_id_tag(self) -> str:
        return "1"

    def get_state(self) -> str:
        return model.Job.states.QUEUED

    def prepare(self) -> None:
        raise self.refusal

    def fail(self, message: str, **kwargs: Any) -> None:
        self.failures.append((message, kwargs))


class NoDefaultsRunner(BaseJobRunner):
    def __init__(self) -> None:
        pass

    def _populate_parameter_defaults(self, job_destination: Any) -> bool:
        return False


@pytest.mark.parametrize(
    "refusal",
    [InsufficientPermissionsException("Container 'busybox' is not allowed"), ToolInputRejected("Not run.", ["code"])],
    ids=["container", "security-review"],
)
def test_runner_fails_a_refused_job_without_an_error(refusal: Exception) -> None:
    job_wrapper = RefusingJobWrapper(refusal)
    assert NoDefaultsRunner().prepare_job(cast(Any, job_wrapper)) is False
    assert job_wrapper.failures == [(str(refusal), {"exception": False})]
