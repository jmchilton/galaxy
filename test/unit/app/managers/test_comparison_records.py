from datetime import datetime

import pytest

from galaxy.managers.comparison_records import (
    ImplicitCollectionJobsRecord,
    JobRecord,
    submission_key,
)
from galaxy.managers.comparisons import ToolRunPageRow
from galaxy.schema.fields import Security
from galaxy.security.idencoding import IdEncodingHelper

JOB = JobRecord(id=7, state="ok", tool_id="cat1", tool_version="1.0", copied=True)


@pytest.fixture(autouse=True)
def id_encoding() -> None:
    Security.security = IdEncodingHelper(id_secret="testing")


def _batch(
    populated_state: str = "ok", states: dict[str, int] | None = None, copied: int = 0, representative=JOB
) -> ImplicitCollectionJobsRecord:
    states = states or {}
    return ImplicitCollectionJobsRecord(
        id=3,
        populated_state=populated_state,
        representative=representative if states else None,
        states=states,
        job_count=sum(states.values()),
        copied_count=copied,
    )


@pytest.mark.parametrize(
    "populated_state,states,expected",
    [
        ("ok", {}, "ok"),
        ("failed", {}, "error"),
        ("new", {}, "new"),
        ("ok", {"ok": 1, "error": 1}, "error"),
        ("ok", {"skipped": 2}, "skipped"),
    ],
)
def test_batch_state(populated_state, states, expected) -> None:
    assert _batch(populated_state, states).state == expected


def test_reused() -> None:
    assert JOB.reused == "yes"
    assert JOB._replace(copied=False).reused == "no"
    assert _batch().reused is None
    assert _batch(states={"ok": 2}, copied=1).reused == "partial"


def test_outputs_skipped_only_for_a_skipped_job() -> None:
    assert JOB._replace(state="skipped").outputs_skipped
    assert not JOB.outputs_skipped
    assert not _batch(states={"skipped": 2}).outputs_skipped


def test_batch_tool_comes_from_its_first_job() -> None:
    assert (_batch().tool_id, _batch().tool_version) == (None, None)
    batch = _batch(states={"ok": 1})
    assert (batch.tool_id, batch.tool_version) == ("cat1", "1.0")


def test_run_refs() -> None:
    assert JOB.run_ref().model_dump()["model"] == "Job"
    ref = _batch(states={"ok": 2}).run_ref().model_dump()
    assert (ref["model"], ref["job_count"], ref["states"]) == ("ImplicitCollectionJobs", 2, {"ok": 2})


def test_submission_key() -> None:
    assert submission_key(1, 2) == ("icj", 2)
    assert submission_key(1, None) == ("job", 1)
    assert submission_key(None, None) is None
    now = datetime.now()
    row = ToolRunPageRow(5, None, now, now, 1, "h", False, False)
    assert row.submission_key == ("job", 5)
    assert row._replace(implicit_collection_jobs_id=9).submission_key == ("icj", 9)
