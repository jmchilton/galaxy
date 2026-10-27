"""Pure helpers for building comparison table columns; no database access."""

import re
from collections.abc import Mapping
from typing import (
    Any,
    NamedTuple,
)

from galaxy.schema.comparisons import (
    ComparisonColumn,
    ComparisonColumnRole,
    MissingReason,
    ReusedState,
)
from galaxy.schema.states import JobState

NEW_PRIMARY_FILE_PREFIX = "__new_primary_file_"
PART_SEPARATOR = "|__part__|"
ERROR_STATES = (JobState.ERROR, JobState.FAILED, JobState.DELETED)
RUNNING_STATES = (JobState.RUNNING, JobState.FINISHING)
QUEUED_STATES = (JobState.QUEUED, JobState.WAITING, JobState.RESUBMITTED, JobState.UPLOAD)
OTHER_STATES = (JobState.PAUSED, JobState.STOPPING, JobState.STOPPED, JobState.DELETING)
TRAILING_DIGITS = re.compile(r"\d+$")


class ColumnSpec(NamedTuple):
    key: str
    label: str
    role: ComparisonColumnRole


def normalize_io_name(name: str) -> str:
    """Fold discovered-primary and split-part association names to the declared output name."""
    if name.startswith(NEW_PRIMARY_FILE_PREFIX) and "|" in name:
        return name[len(NEW_PRIMARY_FILE_PREFIX) :].split("|", 1)[0]
    if PART_SEPARATOR in name:
        return name.split(PART_SEPARATOR, 1)[0]
    return name


def multiple_input_aliases(ids_by_name: Mapping[str, Any]) -> set[str]:
    """Names a multiple data param records per dataset (``name1``, ``name2``...) next to ``name``."""
    aliases = set()
    for name in ids_by_name:
        match = TRAILING_DIGITS.search(name)
        if not match:
            continue
        # a name like f11 may be f1 + 1 or f + 11; try every split
        for split in range(match.start(), len(name)):
            base = name[:split]
            first = f"{base}1"
            if base and base in ids_by_name and first in ids_by_name and ids_by_name[base] == ids_by_name[first]:
                aliases.add(name)
                break
    return aliases


def align_columns(declared: Mapping[int, list[ColumnSpec]], newest_version: int) -> list[ComparisonColumn]:
    """Union of per-version columns, ordered by the newest version, with older-only columns last."""
    versions_by_key: dict[str, set[int]] = {}
    specs: dict[str, ColumnSpec] = {}
    duplicates: set[str] = set()
    order: list[str] = []
    ordered_versions = sorted(declared, key=lambda version: (version != newest_version, -version))
    for version in ordered_versions:
        seen_in_version: set[str] = set()
        for spec in declared[version]:
            if spec.key in seen_in_version:
                duplicates.add(spec.key)
                continue
            seen_in_version.add(spec.key)
            if spec.key not in specs:
                specs[spec.key] = spec
                order.append(spec.key)
            versions_by_key.setdefault(spec.key, set()).add(version)
    all_versions = set(declared)
    return [
        ComparisonColumn(
            key=key,
            label=specs[key].label,
            role=specs[key].role,
            present_in_versions=None if versions_by_key[key] == all_versions else sorted(versions_by_key[key]),
            duplicate=key in duplicates,
        )
        for key in order
    ]


def missing_reason(
    column_in_version: bool, step_state: str | None, job_state: str | None, run_terminal: bool
) -> MissingReason:
    """Why a row has no value for a column; ``step_state`` is None when the step has not been scheduled."""
    if not column_in_version:
        return "not_in_version"
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


def summary_state(states: Mapping[str, int]) -> str:
    """Single state for a mapped batch from per-state job counts; mirrors the client's JobStateSummary."""
    present = {state for state, count in states.items() if count}
    if not present:
        return JobState.NEW.value
    if present.intersection(ERROR_STATES):
        return JobState.ERROR.value
    if present.intersection(RUNNING_STATES):
        return JobState.RUNNING.value
    if present.intersection(QUEUED_STATES):
        return JobState.QUEUED.value
    if JobState.NEW in present:
        return JobState.NEW.value
    for state in OTHER_STATES:
        if state in present:
            return state.value
    if present == {JobState.SKIPPED}:
        return JobState.SKIPPED.value
    return JobState.OK.value
