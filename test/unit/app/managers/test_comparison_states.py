import pytest

from galaxy.managers.comparison_states import (
    missing_reason,
    reused_state,
    summary_state,
)


@pytest.mark.parametrize(
    "step_state,job_state,run_terminal,expected",
    [
        (None, None, False, "not_run_yet"),
        (None, None, True, "not_run_yet"),
        ("scheduled", "skipped", True, "skipped"),
        ("scheduled", "running", False, "not_run_yet"),
        ("scheduled", "ok", True, "no_output"),
        ("scheduled", "error", True, "no_output"),
        ("scheduled", None, True, "no_output"),
    ],
)
def test_missing_reason(step_state, job_state, run_terminal, expected):
    assert missing_reason(step_state, job_state, run_terminal) == expected


@pytest.mark.parametrize(
    "copied,total,expected",
    [(0, 3, "no"), (1, 3, "partial"), (3, 3, "yes"), (0, 0, "no"), (1, 1, "yes")],
)
def test_reused_state(copied, total, expected):
    assert reused_state(copied, total) == expected


@pytest.mark.parametrize(
    "states,expected",
    [
        ({}, "new"),
        ({"ok": 3}, "ok"),
        ({"ok": 2, "error": 1}, "error"),
        ({"ok": 1, "failed": 1}, "error"),
        ({"ok": 1, "running": 1, "queued": 1}, "running"),
        ({"ok": 1, "queued": 2}, "queued"),
        ({"new": 2}, "new"),
        ({"new": 1, "queued": 1}, "queued"),
        ({"ok": 1, "skipped": 1}, "ok"),
        ({"skipped": 2}, "skipped"),
        ({"ok": 1, "paused": 1}, "paused"),
    ],
)
def test_summary_state(states, expected):
    assert summary_state(states) == expected
