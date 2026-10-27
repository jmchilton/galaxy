"""Pure helpers for the state, reuse and missing reason a comparison row shows; no database access."""

from collections.abc import (
    Collection,
    Mapping,
)

from galaxy.schema.comparisons import (
    MissingReason,
    ReusedState,
)
from galaxy.schema.states import (
    DatasetCollectionPopulatedState,
    JobState,
)

ERROR_STATES = (JobState.ERROR, JobState.FAILED, JobState.DELETED)
RUNNING_STATES = (JobState.RUNNING, JobState.FINISHING)
QUEUED_STATES = (JobState.QUEUED, JobState.WAITING, JobState.RESUBMITTED, JobState.UPLOAD)
OTHER_STATES = (JobState.PAUSED, JobState.STOPPING, JobState.STOPPED, JobState.DELETING)
# a mapped batch shows the first group any member job is in, else skipped when all are, else ok
SUMMARY_STATE_GROUPS: tuple[tuple[str, tuple[JobState, ...]], ...] = (
    (JobState.ERROR.value, ERROR_STATES),
    (JobState.RUNNING.value, RUNNING_STATES),
    (JobState.QUEUED.value, QUEUED_STATES),
    (JobState.NEW.value, (JobState.NEW,)),
    *((state.value, (state,)) for state in OTHER_STATES),
)
SUMMARY_OK_RANK = len(SUMMARY_STATE_GROUPS)
SUMMARY_SKIPPED_RANK = SUMMARY_OK_RANK + 1
SUMMARY_STATES = (*(label for label, _ in SUMMARY_STATE_GROUPS), JobState.OK.value, JobState.SKIPPED.value)
# state of a mapped batch without jobs, e.g. mapped over an empty collection; others are new
EMPTY_BATCH_STATES = {
    DatasetCollectionPopulatedState.OK.value: JobState.OK.value,
    DatasetCollectionPopulatedState.FAILED.value: JobState.ERROR.value,
}


def missing_reason(step_state: str | None, job_state: str | None, run_terminal: bool) -> MissingReason:
    """Why a row has no value for a column its version has; ``step_state`` is None when the step has not been scheduled."""
    if step_state is None:
        return "not_run_yet"
    if job_state == JobState.SKIPPED:
        return "skipped"
    if not run_terminal:
        return "not_run_yet"
    return "no_output"


def reused_state(copied: int, total: int) -> ReusedState:
    """Job cache reuse of a submission from its copied and total job counts."""
    if copied == 0 or total == 0:
        return "no"
    return "yes" if copied >= total else "partial"


def summary_rank(state: str | None) -> int:
    """Precedence of a member job's state in its batch's summary state; the lowest rank wins."""
    for rank, (_, states) in enumerate(SUMMARY_STATE_GROUPS):
        if state in states:
            return rank
    return SUMMARY_SKIPPED_RANK if state == JobState.SKIPPED else SUMMARY_OK_RANK


def summary_ranks(states: Collection[str]) -> list[int]:
    """Ranks whose summary state is one of ``states``."""
    return [rank for rank, state in enumerate(SUMMARY_STATES) if state in states]


def summary_state(states: Mapping[str, int]) -> str:
    """Single state for a mapped batch from per-state job counts; mirrors the client's JobStateSummary."""
    present = [state for state, count in states.items() if count]
    if not present:
        return JobState.NEW.value
    return SUMMARY_STATES[min(summary_rank(state) for state in present)]
