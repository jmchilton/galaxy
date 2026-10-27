import pytest

from galaxy.managers.comparison_columns import (
    align_columns,
    ColumnSpec,
    keyed_io,
    multiple_input_members,
    normalize_io_name,
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


def test_keyed_io_prefers_exact_name_over_folded():
    items = {"__new_primary_file_out|a__": 1, "out": 2, "other|__part__|forward": 3}
    assert keyed_io("output", items) == {"output:out": 2, "output:other": 3}


@pytest.mark.parametrize(
    "key,expected",
    [
        ("input:in|x", ColumnSpec("input:in|x", "in|x", "input")),
        ("parameter:p", ColumnSpec("parameter:p", "p", "parameter")),
        ("output:a:b", ColumnSpec("output:a:b", "a:b", "output")),
    ],
)
def test_column_spec_of_key(key, expected):
    assert ColumnSpec.of_key(key) == expected
