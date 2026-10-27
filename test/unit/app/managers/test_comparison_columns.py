import pytest

from galaxy.managers.comparison_columns import (
    align_columns,
    ColumnSpec,
    missing_reason,
    multiple_input_members,
    normalize_io_name,
    reused_state,
    summary_state,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("out_file1", "out_file1"),
        ("queries_0|input2", "queries_0|input2"),
        ("__new_primary_file_sample|sample2__", "sample"),
        ("__new_primary_file_sample|sample3__", "sample"),
        ("output|__part__|forward", "output"),
        ("__new_primary_file_", "__new_primary_file_"),
    ],
)
def test_normalize_io_name(raw, expected):
    assert normalize_io_name(raw) == expected


def test_multiple_input_members_from_multi_data_param():
    # names and identities as recorded for multi_data_param with f1=[a, b], f2=a
    ids = {"f1": 1, "f11": 1, "f12": 2, "f2": 1, "f21": 1}
    assert multiple_input_members(ids) == {"f1": ["f11", "f12"], "f2": ["f21"]}


def test_multiple_input_members_in_dataset_order():
    names = [f"f1{index}" for index in range(1, 12)]
    ids = {"f1": 1, **{name: index for index, name in enumerate(names, start=1)}}
    assert multiple_input_members(dict(reversed(ids.items()))) == {"f1": names}


def test_multiple_input_members_keeps_distinct_numbered_inputs():
    assert multiple_input_members({"input": 1, "input1": 2}) == {}
    assert multiple_input_members({"input1": 1, "queries_0|input2": 2}) == {}


def _spec(name, role="output"):
    return ColumnSpec(key=f"{role}:{name}", label=name, role=role)


def test_align_columns_orders_by_newest_version():
    declared = {
        2: [_spec("a", "input"), _spec("c"), _spec("b")],
        1: [_spec("a", "input"), _spec("b"), _spec("c")],
    }
    columns = align_columns(declared, newest_version=2)
    assert [c.key for c in columns] == ["input:a", "output:c", "output:b"]
    assert all(c.present_in_versions is None for c in columns)
    assert not any(c.duplicate for c in columns)


def test_align_columns_puts_old_only_columns_last():
    declared = {
        3: [_spec("new"), _spec("both")],
        1: [_spec("old"), _spec("both")],
        0: [_spec("older"), _spec("old")],
    }
    columns = align_columns(declared, newest_version=3)
    assert [c.key for c in columns] == ["output:new", "output:both", "output:old", "output:older"]
    by_key = {c.key: c for c in columns}
    assert by_key["output:new"].present_in_versions == [3]
    assert by_key["output:both"].present_in_versions == [1, 3]
    assert by_key["output:old"].present_in_versions == [0, 1]
    assert by_key["output:older"].present_in_versions == [0]


def test_align_columns_flags_duplicates():
    declared = {0: [_spec("n"), _spec("n"), _spec("m")]}
    columns = align_columns(declared, newest_version=0)
    assert [c.key for c in columns] == ["output:n", "output:m"]
    assert columns[0].duplicate
    assert not columns[1].duplicate


def test_align_columns_empty():
    assert align_columns({}, newest_version=0) == []


@pytest.mark.parametrize(
    "column_in_version,step_state,job_state,run_terminal,expected",
    [
        (False, "scheduled", "ok", True, "not_in_version"),
        (False, None, None, False, "not_in_version"),
        (True, None, None, False, "not_run_yet"),
        (True, None, None, True, "not_run_yet"),
        (True, "scheduled", "skipped", True, "skipped"),
        (True, "scheduled", "running", False, "not_run_yet"),
        (True, "scheduled", "ok", True, "no_output"),
        (True, "scheduled", "error", True, "no_output"),
        (True, "scheduled", None, True, "no_output"),
    ],
)
def test_missing_reason(column_in_version, step_state, job_state, run_terminal, expected):
    assert missing_reason(column_in_version, step_state, job_state, run_terminal) == expected


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
