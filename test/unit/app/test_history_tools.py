"""Unit tests for history_tools helper functions.

Tests the standalone helper functions using mocked SQLAlchemy sessions.
These helpers are the data access layer for the notebook assistant agent.
"""

from unittest import mock

import pytest

pydantic_ai = pytest.importorskip("pydantic_ai")

from galaxy.agents.history_tools import (
    _format_size,
    get_collection_structure,
    get_dataset_info,
    get_dataset_peek,
    list_history_items,
)


class TestFormatSize:
    def test_none(self):
        assert _format_size(None) == ""

    def test_negative(self):
        assert _format_size(-1) == ""

    def test_zero(self):
        assert _format_size(0) == "0B"

    def test_bytes(self):
        assert _format_size(512) == "512B"

    def test_kilobytes(self):
        assert _format_size(1024) == "1.0KB"

    def test_megabytes(self):
        assert _format_size(1_500_000) == "1.4MB"

    def test_gigabytes(self):
        assert _format_size(2_147_483_648) == "2.0GB"


def _make_hda_row(hid, name="test.txt", ext="txt", state="ok", deleted=False, visible=True, file_size=1024):
    """Create a mock HDA query row."""
    return (hid, name, ext, state, deleted, visible, file_size)


def _make_hdca_row(hid, name="Collection", collection_type="list", deleted=False, visible=True):
    """Create a mock HDCA query row."""
    return (hid, name, collection_type, deleted, visible)


class TestListHistoryItems:
    @pytest.mark.asyncio
    async def test_empty_history(self):
        session = mock.Mock()
        session.execute.return_value.all.return_value = []
        result = await list_history_items(session, history_id=1)
        assert result == "No items found in history."

    @pytest.mark.asyncio
    async def test_datasets_and_collections(self):
        session = mock.Mock()
        # First call returns HDA rows, second returns HDCA rows
        hda_results = mock.Mock()
        hda_results.all.return_value = [
            _make_hda_row(1, "reads.fastq", "fastqsanger", "ok", file_size=1_200_000_000),
            _make_hda_row(3, "mapping.bam", "bam", "ok", file_size=2_300_000_000),
        ]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = [
            _make_hdca_row(2, "Paired Reads", "list:paired"),
        ]
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1)
        lines = result.split("\n")

        assert "3 shown" in lines[0]
        assert "HID 1: reads.fastq [dataset, fastqsanger]" in lines[1]
        assert "HID 2: Paired Reads [collection, list:paired]" in lines[2]
        assert "HID 3: mapping.bam [dataset, bam]" in lines[3]

    @pytest.mark.asyncio
    async def test_filters_deleted(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [
            _make_hda_row(1, "active.txt", deleted=False),
            _make_hda_row(2, "deleted.txt", deleted=True),
        ]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = []
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1, include_deleted=False)
        assert "HID 1" in result
        assert "HID 2" not in result

    @pytest.mark.asyncio
    async def test_includes_deleted_when_asked(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [
            _make_hda_row(1, "active.txt", deleted=False),
            _make_hda_row(2, "deleted.txt", deleted=True),
        ]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = []
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1, include_deleted=True)
        assert "HID 1" in result
        assert "HID 2" in result

    @pytest.mark.asyncio
    async def test_filters_hidden(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [
            _make_hda_row(1, "visible.txt", visible=True),
            _make_hda_row(2, "hidden.txt", visible=False),
        ]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = []
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1, include_hidden=False)
        assert "HID 1" in result
        assert "HID 2" not in result

    @pytest.mark.asyncio
    async def test_pagination(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [_make_hda_row(i, f"file{i}.txt") for i in range(1, 6)]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = []
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1, offset=2, limit=2)
        assert "2 shown" in result
        assert "total=5" in result
        assert "HID 3" in result
        assert "HID 4" in result
        assert "HID 1" not in result

    @pytest.mark.asyncio
    async def test_limit_capped_at_200(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [_make_hda_row(i, f"file{i}.txt") for i in range(1, 4)]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = []
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1, limit=500)
        # All 3 items shown (limit capped to 200, but only 3 items exist)
        assert "3 shown" in result

    @pytest.mark.asyncio
    async def test_sorted_by_hid(self):
        session = mock.Mock()
        hda_results = mock.Mock()
        hda_results.all.return_value = [
            _make_hda_row(3, "third.txt"),
            _make_hda_row(1, "first.txt"),
        ]
        hdca_results = mock.Mock()
        hdca_results.all.return_value = [
            _make_hdca_row(2, "second"),
        ]
        session.execute.side_effect = [hda_results, hdca_results]

        result = await list_history_items(session, history_id=1)
        lines = result.split("\n")
        assert "HID 1" in lines[1]
        assert "HID 2" in lines[2]
        assert "HID 3" in lines[3]


class TestGetDatasetInfo:
    def _mock_session_with_hda(self, hda):
        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = hda
        return session

    def _mock_session_not_found(self):
        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        return session

    @pytest.mark.asyncio
    async def test_hda_basic(self):
        hda = mock.Mock()
        hda.name = "reads.fastq"
        hda.extension = "fastqsanger"
        hda.state = "ok"
        hda.get_size.return_value = 1_200_000_000
        hda.create_time = None
        hda.info = None
        hda.creating_job = None
        hda.metadata = None
        hda.deleted = False
        hda.visible = True

        session = self._mock_session_with_hda(hda)
        result = await get_dataset_info(session, history_id=1, hid=1)

        assert "reads.fastq" in result
        assert "fastqsanger" in result
        assert "ok" in result
        assert "1.1GB" in result

    @pytest.mark.asyncio
    async def test_hda_with_creating_job(self):
        hda = mock.Mock()
        hda.name = "mapping.bam"
        hda.extension = "bam"
        hda.state = "ok"
        hda.get_size.return_value = 0
        hda.create_time = None
        hda.info = None
        hda.creating_job = mock.Mock()
        hda.creating_job.tool_id = "bwa_mem"
        hda.creating_job.tool_version = "0.7.17"
        hda.metadata = None
        hda.deleted = False
        hda.visible = True

        session = self._mock_session_with_hda(hda)
        result = await get_dataset_info(session, history_id=1, hid=2)

        assert "bwa_mem" in result
        assert "0.7.17" in result

    @pytest.mark.asyncio
    async def test_not_found(self):
        session = self._mock_session_not_found()
        result = await get_dataset_info(session, history_id=1, hid=99)
        assert "No dataset or collection found" in result


class TestGetDatasetPeek:
    @pytest.mark.asyncio
    async def test_with_peek(self):
        hda = mock.Mock()
        hda.name = "data.tsv"
        hda.extension = "tabular"
        hda.peek = "<table><tr><td>col1</td><td>col2</td></tr></table>"

        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = hda

        result = await get_dataset_peek(session, history_id=1, hid=1)
        assert "col1" in result
        assert "col2" in result
        assert "<table>" not in result  # HTML stripped

    @pytest.mark.asyncio
    async def test_no_peek(self):
        hda = mock.Mock()
        hda.name = "data.bam"
        hda.extension = "bam"
        hda.peek = None

        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = hda

        result = await get_dataset_peek(session, history_id=1, hid=1)
        assert "No preview available" in result

    @pytest.mark.asyncio
    async def test_not_found(self):
        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = None

        result = await get_dataset_peek(session, history_id=1, hid=99)
        assert "No dataset found" in result


class TestGetCollectionStructure:
    @pytest.mark.asyncio
    async def test_list_collection(self):
        elem1 = mock.Mock()
        elem1.element_identifier = "forward"
        elem1.hda = mock.Mock(name="read1.fastq", extension="fastqsanger", state="ok")
        elem1.hda.name = "read1.fastq"
        elem1.hda.extension = "fastqsanger"
        elem1.hda.state = "ok"
        elem1.child_collection = None

        elem2 = mock.Mock()
        elem2.element_identifier = "reverse"
        elem2.hda = mock.Mock()
        elem2.hda.name = "read2.fastq"
        elem2.hda.extension = "fastqsanger"
        elem2.hda.state = "ok"
        elem2.child_collection = None

        collection = mock.Mock()
        collection.collection_type = "paired"
        collection.elements = [elem1, elem2]

        hdca = mock.Mock()
        hdca.name = "Paired Reads"
        hdca.collection = collection

        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = hdca

        result = await get_collection_structure(session, history_id=1, hid=2)
        assert "Paired Reads" in result
        assert "paired" in result
        assert "Elements: 2" in result
        assert "forward" in result
        assert "reverse" in result

    @pytest.mark.asyncio
    async def test_not_found(self):
        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = None

        result = await get_collection_structure(session, history_id=1, hid=99)
        assert "No collection found" in result

    @pytest.mark.asyncio
    async def test_max_elements(self):
        elements = []
        for i in range(5):
            elem = mock.Mock()
            elem.element_identifier = f"elem_{i}"
            elem.hda = mock.Mock()
            elem.hda.name = f"file_{i}.txt"
            elem.hda.extension = "txt"
            elem.hda.state = "ok"
            elem.child_collection = None
            elements.append(elem)

        collection = mock.Mock()
        collection.collection_type = "list"
        collection.elements = elements

        hdca = mock.Mock()
        hdca.name = "Big Collection"
        hdca.collection = collection

        session = mock.Mock()
        session.execute.return_value.scalar_one_or_none.return_value = hdca

        result = await get_collection_structure(session, history_id=1, hid=1, max_elements=3)
        assert "elem_0" in result
        assert "elem_2" in result
        assert "elem_3" not in result
        assert "2 more elements" in result
