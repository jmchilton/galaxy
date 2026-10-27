import pytest

from galaxy.managers.comparison_records import (
    ImplicitCollectionJobsRecord,
    submission_key,
)


@pytest.mark.parametrize(
    "populated_state,expected",
    [
        ("failed", "error"),
        ("new", "new"),
    ],
)
def test_empty_batch_state(populated_state, expected) -> None:
    batch = ImplicitCollectionJobsRecord(
        id=3, populated_state=populated_state, representative=None, states={}, job_count=0, copied_count=0
    )
    assert batch.state == expected


def test_submission_key() -> None:
    assert submission_key(1, 2) == ("icj", 2)
    assert submission_key(1, None) == ("job", 1)
    assert submission_key(None, None) is None
