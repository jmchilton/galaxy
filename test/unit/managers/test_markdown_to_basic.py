import os
import tempfile
from contextlib import contextmanager

import mock

from galaxy import model
from galaxy.managers.markdown_util import to_basic_markdown
from .base import BaseTestCase


class MarkdownToBasicTestCase(BaseTestCase):

    def setUp(self):
        super(MarkdownToBasicTestCase, self).setUp()
        self.test_dataset_path = None
        self.app.hda_manager = mock.MagicMock()
        self.app.workflow_manager = mock.MagicMock()
        self.app.history_manager = mock.MagicMock()

    def tearDown(self):
        super(MarkdownToBasicTestCase, self).tearDown()
        if self.test_dataset_path is not None:
            os.remove(self.test_dataset_path)

    def test_noop_on_non_galaxy_blocks(self):
        example = """# Example

## Some Syntax

*Foo* **bar** [Google](http://google.com/).

## Code Blocks

```
history_dataset_display(history_dataset_id=4)
```

Another kind of code block:

    job_metrics(job_id=4)

"""
        result = self._to_basic(example)
        assert result == example

    def test_history_dataset_peek(self):
        hda = model.HistoryDatasetAssociation()
        hda.peek = "My Cool Peek"
        example = """# Example
```galaxy
history_dataset_peek(history_dataset_id=1)
```
"""
        with self._expect_get_hda(hda):
            result = self._to_basic(example)
        assert '\n    My Cool Peek\n\n' in result

    def test_history_dataset_peek_empty(self):
        hda = self._new_hda()
        example = """# Example
```galaxy
history_dataset_peek(history_dataset_id=1)
```
"""
        with self._expect_get_hda(hda):
            result = self._to_basic(example)
        assert '\n*No Dataset Peek Available*\n' in result

    def test_history_display_binary(self):
        hda = self._new_hda()
        hda.extension = 'ab1'
        example = """# Example
```galaxy
history_dataset_display(history_dataset_id=1)
```
"""
        with self._expect_get_hda(hda):
            result = self._to_basic(example)
        assert "Contents:\n*cannot display binary content*\n" in result

    def test_history_display_text(self):
        hda = self._new_hda(contents="MooCow")
        hda.extension = 'txt'
        example = """# Example
```galaxy
history_dataset_display(history_dataset_id=1)
```
"""
        with self._expect_get_hda(hda):
            result = self._to_basic(example)
        assert "Contents:\n\n    MooCow\n\n" in result

    def test_history_display_gtf(self):
        gtf = """chr13	Cufflinks	transcript	3405463	3405542	1000	.	.	gene_id "CUFF.50189"; transcript_id "CUFF.50189.1"; FPKM "6.3668918357"; frac "1.000000"; conf_lo "0.000000"; conf_hi "17.963819"; cov "0.406914";
chr13	Cufflinks	exon	3405463	3405542	1000	.	.	gene_id "CUFF.50189"; transcript_id "CUFF.50189.1"; exon_number "1"; FPKM "6.3668918357"; frac "1.000000"; conf_lo "0.000000"; conf_hi "17.963819"; cov "0.406914";
chr13	Cufflinks	transcript	3473337	3473372	1000	.	.	gene_id "CUFF.50191"; transcript_id "CUFF.50191.1"; FPKM "11.7350749444"; frac "1.000000"; conf_lo "0.000000"; conf_hi "35.205225"; cov "0.750000";
"""
        example = """# Example
```galaxy
history_dataset_display(history_dataset_id=1)
```
"""
        hda = self._new_hda(contents=gtf)
        hda.extension = 'gtf'
        from galaxy.datatypes.tabular import Tabular
        assert isinstance(hda.datatype, Tabular)
        with self._expect_get_hda(hda):
            result = self._to_basic(example)
        assert '<table' in result

    def _new_hda(self, contents=None):
        hda = model.HistoryDatasetAssociation()
        if contents is not None:
            hda.dataset = mock.MagicMock()
            hda.dataset.purged = False
            t = tempfile.NamedTemporaryFile(mode="w", delete=False)
            t.write(contents)
            hda.dataset.get_file_name.return_value = t.name
        return hda

    @contextmanager
    def _expect_get_hda(self, hda, hda_id=1):
        self.app.hda_manager.get_accessible.return_value = hda
        yield
        self.app.hda_manager.get_accessible.assert_called_once_with(hda_id, self.trans.user)

    def _to_basic(self, example):
        return to_basic_markdown(self.trans, example)
