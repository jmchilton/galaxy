import pytest

from galaxy.managers.comparison_cells import (
    fill_cells,
    ItemCell,
    RowIo,
)
from galaxy.managers.comparison_records import (
    IoValue,
    ItemRef,
    ItemRefs,
)
from galaxy.schema.comparisons import (
    ComparisonColumn,
    DatasetCell,
    MissingCell,
    ValueCell,
)
from galaxy.schema.fields import Security
from galaxy.security.idencoding import IdEncodingHelper


@pytest.fixture(autouse=True)
def id_encoding():
    Security.security = IdEncodingHelper(id_secret="testing")


def _dataset(hda_id: int) -> DatasetCell:
    return DatasetCell(id=hda_id, hid=hda_id, state="ok", deleted=False, purged=False, history_id=1)


def _columns() -> list[ComparisonColumn]:
    return [
        ComparisonColumn(key="input:a", label="a", role="input"),
        ComparisonColumn(key="input:list", label="list", role="input"),
        ComparisonColumn(key="parameter:p", label="p", role="parameter"),
        ComparisonColumn(key="output:new", label="new", role="output"),
    ]


def _item_cells() -> dict[ItemRef, ItemCell]:
    return {
        ItemRef("hda", 1): ItemCell(_dataset(1), ["data_lines"]),
        ItemRef("hda", 2): ItemCell(_dataset(2), ["columns", "data_lines"]),
    }


def test_fill_cells_resolves_items_lists_and_values():
    columns = _columns()
    io: dict[str, IoValue] = {
        "input:a": ItemRef("hda", 1),
        "input:list": ItemRefs((ItemRef("hda", 1), ItemRef("hda", 2), ItemRef("hda", 9))),
        "parameter:p": ValueCell(value=3, source="parameter"),
    }
    [cells] = fill_cells(columns, [RowIo(io, None, "no_output")], _item_cells())
    assert cells["input:a"] == _dataset(1)
    assert cells["input:list"].model_dump()["items"] == [_dataset(1).model_dump(), _dataset(2).model_dump()]
    assert cells["parameter:p"] == ValueCell(value=3, source="parameter")
    assert cells["output:new"] == MissingCell(reason="no_output")
    assert [column.metadata_keys for column in columns] == [["data_lines"], ["columns", "data_lines"], [], []]


def test_fill_cells_marks_columns_outside_the_row_version():
    io: dict[str, IoValue] = {"input:a": ItemRef("hda", 404)}
    [cells] = fill_cells(_columns(), [RowIo(io, {"input:a", "output:new"}, "not_run_yet")], _item_cells())
    assert cells["input:a"] == MissingCell(reason="not_run_yet")
    assert cells["output:new"] == MissingCell(reason="not_run_yet")
    assert cells["input:list"] == MissingCell(reason="not_in_version")
    assert cells["parameter:p"] == MissingCell(reason="not_in_version")
