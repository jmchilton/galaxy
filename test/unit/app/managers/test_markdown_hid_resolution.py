"""Unit tests for HID resolution in history notebooks."""

from unittest import mock

import pytest

from galaxy import model
from galaxy.managers.markdown_util import (
    _resolve_hid,
    _resolve_hid_to_collection,
    _resolve_hid_to_dataset,
    HID_COLLECTION_DIRECTIVES,
    HID_DATASET_DIRECTIVES,
    HID_DIRECTIVES,
    resolve_history_markdown,
)
from .base import BaseTestCase


class TestHidDirectiveConstants(BaseTestCase):
    """Tests for HID directive constant definitions."""

    def test_dataset_directives_complete(self):
        """Verify HID_DATASET_DIRECTIVES contains all expected directives."""
        expected = {
            "history_dataset_as_image",
            "history_dataset_as_table",
            "history_dataset_display",
            "history_dataset_embedded",
            "history_dataset_index",
            "history_dataset_info",
            "history_dataset_link",
            "history_dataset_name",
            "history_dataset_peek",
            "history_dataset_type",
        }
        assert HID_DATASET_DIRECTIVES == expected

    def test_collection_directives_complete(self):
        """Verify HID_COLLECTION_DIRECTIVES contains expected directives."""
        expected = {"history_dataset_collection_display"}
        assert HID_COLLECTION_DIRECTIVES == expected

    def test_hid_directives_is_union(self):
        """Verify HID_DIRECTIVES is union of dataset and collection directives."""
        assert HID_DIRECTIVES == HID_DATASET_DIRECTIVES | HID_COLLECTION_DIRECTIVES


class TestResolveHidToDataset(BaseTestCase):
    """Tests for _resolve_hid_to_dataset function."""

    def setUp(self):
        super().setUp()
        self.history_id = 1

    def test_resolve_existing_dataset(self):
        """Test resolving HID to existing dataset ID."""
        # Mock query returning (id, deleted) tuple
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = _resolve_hid_to_dataset(
            self.trans.sa_session, self.history_id, 5, "history_dataset_display"
        )
        assert result == 100

    def test_resolve_deleted_dataset_raises(self):
        """Test that resolving deleted dataset raises ValueError."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, True)  # deleted=True
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_dataset(
                self.trans.sa_session, self.history_id, 5, "history_dataset_display"
            )
        assert "deleted" in str(exc_info.value)

    def test_resolve_nonexistent_dataset_raises(self):
        """Test that resolving nonexistent HID raises ValueError."""
        # First query for HDA returns None, second for HDCA also returns None
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_dataset(
                self.trans.sa_session, self.history_id, 999, "history_dataset_display"
            )
        assert "not found" in str(exc_info.value)

    def test_resolve_collection_as_dataset_raises(self):
        """Test error when HID is a collection but dataset expected."""
        # First query for HDA returns None
        # Second query for HDCA returns a hit (it's a collection)
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
            mock.MagicMock(first=mock.MagicMock(return_value=(200,))),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_dataset(
                self.trans.sa_session, self.history_id, 5, "history_dataset_display"
            )
        assert "is a collection" in str(exc_info.value)
        assert "expects a dataset" in str(exc_info.value)


class TestResolveHidToCollection(BaseTestCase):
    """Tests for _resolve_hid_to_collection function."""

    def setUp(self):
        super().setUp()
        self.history_id = 1

    def test_resolve_existing_collection(self):
        """Test resolving HID to existing collection ID."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (200, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = _resolve_hid_to_collection(
            self.trans.sa_session,
            self.history_id,
            10,
            "history_dataset_collection_display",
        )
        assert result == 200

    def test_resolve_deleted_collection_raises(self):
        """Test that resolving deleted collection raises ValueError."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (200, True)  # deleted=True
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_collection(
                self.trans.sa_session,
                self.history_id,
                10,
                "history_dataset_collection_display",
            )
        assert "deleted" in str(exc_info.value)

    def test_resolve_nonexistent_collection_raises(self):
        """Test that resolving nonexistent HID raises ValueError."""
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_collection(
                self.trans.sa_session,
                self.history_id,
                999,
                "history_dataset_collection_display",
            )
        assert "not found" in str(exc_info.value)

    def test_resolve_dataset_as_collection_raises(self):
        """Test error when HID is a dataset but collection expected."""
        # First query for HDCA returns None
        # Second query for HDA returns a hit (it's a dataset)
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=None)),
            mock.MagicMock(first=mock.MagicMock(return_value=(100,))),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        with pytest.raises(ValueError) as exc_info:
            _resolve_hid_to_collection(
                self.trans.sa_session,
                self.history_id,
                5,
                "history_dataset_collection_display",
            )
        assert "is a dataset" in str(exc_info.value)
        assert "expects a collection" in str(exc_info.value)


class TestResolveHid(BaseTestCase):
    """Tests for _resolve_hid dispatcher function."""

    def setUp(self):
        super().setUp()
        self.history_id = 1

    def test_resolve_dataset_directive_returns_dataset_arg(self):
        """Test that dataset directives return history_dataset_id."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        arg_name, internal_id = _resolve_hid(
            self.trans.sa_session, self.history_id, 5, "history_dataset_display"
        )
        assert arg_name == "history_dataset_id"
        assert internal_id == 100

    def test_resolve_collection_directive_returns_collection_arg(self):
        """Test that collection directives return history_dataset_collection_id."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (200, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        arg_name, internal_id = _resolve_hid(
            self.trans.sa_session,
            self.history_id,
            10,
            "history_dataset_collection_display",
        )
        assert arg_name == "history_dataset_collection_id"
        assert internal_id == 200

    def test_unsupported_directive_raises(self):
        """Test that unsupported directive raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            _resolve_hid(
                self.trans.sa_session, self.history_id, 5, "job_metrics"
            )
        assert "does not support hid" in str(exc_info.value)

    def test_all_dataset_directives_work(self):
        """Test that all dataset directives are handled correctly."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        for directive in HID_DATASET_DIRECTIVES:
            arg_name, _ = _resolve_hid(
                self.trans.sa_session, self.history_id, 1, directive
            )
            assert arg_name == "history_dataset_id", f"Failed for {directive}"

    def test_all_collection_directives_work(self):
        """Test that all collection directives are handled correctly."""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (200, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        for directive in HID_COLLECTION_DIRECTIVES:
            arg_name, _ = _resolve_hid(
                self.trans.sa_session, self.history_id, 1, directive
            )
            assert arg_name == "history_dataset_collection_id", f"Failed for {directive}"


class TestResolveHistoryMarkdown(BaseTestCase):
    """Tests for resolve_history_markdown function."""

    def setUp(self):
        super().setUp()
        self.history_id = 1

    def test_replaces_single_hid(self):
        """Test replacing a single hid with internal ID."""
        example = """# Analysis
```galaxy
history_dataset_display(hid=42)
```
"""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (999, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "history_dataset_id=999" in result
        assert "hid=42" not in result

    def test_replaces_multiple_hids(self):
        """Test replacing multiple HIDs in same document."""
        example = """
```galaxy
history_dataset_display(hid=1)
```

```galaxy
history_dataset_display(hid=2)
```
"""
        mock_results = [
            mock.MagicMock(first=mock.MagicMock(return_value=(100, False))),
            mock.MagicMock(first=mock.MagicMock(return_value=(200, False))),
        ]
        self.trans.sa_session.execute = mock.MagicMock(side_effect=mock_results)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "history_dataset_id=100" in result
        assert "history_dataset_id=200" in result
        assert "hid=1" not in result
        assert "hid=2" not in result

    def test_preserves_non_galaxy_content(self):
        """Test that non-galaxy markdown content is preserved."""
        example = """# My Analysis

Some **bold** text and *italic* text.

```galaxy
history_dataset_display(hid=5)
```

More content here.
"""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "# My Analysis" in result
        assert "**bold**" in result
        assert "*italic*" in result
        assert "More content here." in result

    def test_handles_collection_hid(self):
        """Test resolving HID for collection directive."""
        example = """
```galaxy
history_dataset_collection_display(hid=7)
```
"""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (300, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "history_dataset_collection_id=300" in result
        assert "hid=7" not in result

    def test_preserves_other_arguments(self):
        """Test that other arguments are preserved when replacing hid."""
        example = """
```galaxy
history_dataset_as_image(hid=5, path="image.png")
```
"""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "history_dataset_id=100" in result
        assert 'path="image.png"' in result
        assert "hid=5" not in result

    def test_no_hid_unchanged(self):
        """Test that content without hid is unchanged."""
        example = """# Plain markdown

```galaxy
history_dataset_display(history_dataset_id=123)
```
"""
        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert result == example

    def test_mixed_hid_and_id(self):
        """Test document with both hid and explicit IDs."""
        example = """
```galaxy
history_dataset_display(hid=5)
```

```galaxy
history_dataset_display(history_dataset_id=999)
```
"""
        mock_result = mock.MagicMock()
        mock_result.first.return_value = (100, False)
        self.trans.sa_session.execute = mock.MagicMock(return_value=mock_result)

        result = resolve_history_markdown(self.trans, self.history_id, example)
        assert "history_dataset_id=100" in result
        assert "history_dataset_id=999" in result
        assert "hid=5" not in result
