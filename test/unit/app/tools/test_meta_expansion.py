"""Job-count previews (summarize_meta_expansion) agree with expand_meta_parameters."""

import copy
from typing import (
    Any,
    cast,
)

import pytest

from galaxy import (
    exceptions,
    model,
)
from galaxy.app_unittest_utils import (
    galaxy_mock,
    tools_support,
)
from galaxy.managers.collections import DatasetCollectionManager
from galaxy.model.dataset_collections import subcollections
from galaxy.tools.parameters.meta import (
    expand_meta_parameters,
    incoming_has_batch,
    summarize_meta_expansion,
)
from galaxy.util.permutations import InputMatchedException
from galaxy.util.unittest import TestCase
from galaxy.work.context import WorkRequestContext

BATCH_TOOL_CONTENTS = """<tool id="batch_tool" name="Batch Tool" version="1.0">
    <command>cat "$input1" > "$out1"</command>
    <inputs>
        <param type="data" name="input1" format="txt" />
        <param type="data" name="input2" format="txt" optional="true" />
        <param type="data_collection" name="pair" collection_type="paired" optional="true" />
    </inputs>
    <outputs>
        <data name="out1" format="txt" />
    </outputs>
</tool>
"""

# Nested collection shape: an int is that many datasets, a list holds one child shape per element.
ShapeT = int | list[Any]


class TestSummarizeMetaExpansion(TestCase, tools_support.UsesTools):
    def setUp(self):
        self.setup_app()
        self.app.dataset_collection_manager = self.app[DatasetCollectionManager]
        self.session = self.app.model.session
        self.history = model.History()
        self.session.add(self.history)
        self.session.commit()
        self.trans = cast(WorkRequestContext, galaxy_mock.MockTrans(app=self.app, history=self.history))
        self._init_tool(BATCH_TOOL_CONTENTS)

    def tearDown(self):
        self.tear_down_app()

    def test_hda_batch(self):
        incoming = {"input1": self._hda_batch(3)}
        self._assert_job_count(incoming, 3)
        assert self._summary(incoming)["inputs"] == [{"name": "input1", "count": 3, "linked": True}]

    def test_list_into_data_input(self):
        self._assert_job_count({"input1": self._hdca_batch("list", 4)}, 4)

    def test_list_list_into_data_input_counts_all_datasets(self):
        self._assert_job_count({"input1": self._hdca_batch("list:list", [3, 2])}, 5)

    def test_list_paired_mapped_over_paired(self):
        incoming = {"input1": self._hda_ref(), "pair": self._hdca_batch("list:paired", [2, 2, 2], "paired")}
        self._assert_job_count(incoming, 3)

    def test_nested_list_list_paired_mapped_over_paired(self):
        incoming = {
            "input1": self._hda_ref(),
            "pair": self._hdca_batch("list:list:paired", [[2, 2], [], [2]], "paired"),
        }
        self._assert_job_count(incoming, 3)

    def test_dce_batch(self):
        outer = self._collection("list:list", [3, 2])
        dce_value = {"src": "dce", "id": self._encode(outer.elements[0].id)}
        self._assert_job_count({"input1": {"batch": True, "values": [dce_value]}}, 3)

    def test_linked_batches_of_equal_length(self):
        incoming = {"input1": self._hdca_batch("list", 3), "input2": self._hda_batch(3)}
        self._assert_job_count(incoming, 3)

    def test_linked_collections_of_equal_length(self):
        incoming = {"input1": self._hdca_batch("list", 3), "input2": self._hdca_batch("list", 3)}
        self._assert_job_count(incoming, 3)

    def test_unlinked_batches_multiply(self):
        incoming = {"input1": self._hda_batch(3, linked=False), "input2": self._hdca_batch("list", 2, linked=False)}
        self._assert_job_count(incoming, 6)
        assert [i["linked"] for i in self._summary(incoming)["inputs"]] == [False, False]

    def test_linked_and_unlinked_batches(self):
        incoming = {"input1": self._hda_batch(3), "input2": self._hda_batch(2, linked=False)}
        self._assert_job_count(incoming, 6)

    def test_empty_collection(self):
        self._assert_job_count({"input1": self._hdca_batch("list", 0)}, 0)

    def test_mismatched_batch_lengths(self):
        incoming = {"input1": self._hda_batch(3), "input2": self._hdca_batch("list", 2)}
        summary = self._summary(incoming)
        assert summary["job_count"] is None
        assert summary["reason"] == "batch_mismatch"
        assert sorted((i["name"], i["count"]) for i in summary["inputs"]) == [("input1", 3), ("input2", 2)]
        with pytest.raises(InputMatchedException):
            self._expand(incoming)

    def test_mismatched_collection_shapes(self):
        incoming = {"input1": self._hdca_batch("list:list", [2, 2]), "input2": self._hdca_batch("list", 4)}
        summary = self._summary(incoming)
        assert summary["job_count"] is None
        assert summary["reason"] == "batch_mismatch"
        with pytest.raises(exceptions.MessageException):
            self._expand(incoming)

    def test_unpopulated_collection(self):
        incoming = {"input1": self._hdca_batch("list", 2, populated=False)}
        summary = self._summary(incoming)
        assert summary["job_count"] is None
        assert summary["reason"] == "inputs_not_ready"
        with pytest.raises(exceptions.ToolInputsNotReadyException):
            self._expand(incoming)

    def test_invalid_map_over_type(self):
        incoming = {"input1": self._hda_ref(), "pair": self._hdca_batch("list:list", [2], "paired")}
        summary = self._summary(incoming)
        assert summary["job_count"] is None
        assert summary["reason"] == "unknown"
        with pytest.raises(exceptions.MessageException):
            self._expand(incoming)

    def test_does_not_mutate_incoming(self):
        incoming = {"input1": self._hda_batch(2), "input1|__identifier__": "foo"}
        before = copy.deepcopy(incoming)
        self._summary(incoming)
        assert incoming == before

    def test_incoming_has_batch(self):
        assert incoming_has_batch({"input1": self._hda_batch(2)})
        assert not incoming_has_batch({"input1": {"batch": False, "values": [self._hda_ref()]}})
        assert not incoming_has_batch({"input1": self._hda_ref(), "tool_version": "1.0"})

    def test_split_count_agrees_with_split(self):
        cases: list[tuple[str, ShapeT, str]] = [
            ("list:paired", [2, 2, 2], "paired"),
            ("list:paired", [2, 2], "single_datasets"),
            ("list", 3, "single_datasets"),
            ("list:list", [3, 0, 1], "list"),
            ("list:list", [3, 0, 1], "single_datasets"),
            ("list:list:paired", [[2, 2], [], [2]], "paired"),
            ("list:list:paired", [[2, 2], [], [2]], "list:paired"),
        ]
        for collection_type, shape, split_type in cases:
            collection = self._collection(collection_type, shape)
            expected = len(subcollections._split_dataset_collection(collection, split_type))
            assert subcollections.split_count(collection, split_type) == expected, (collection_type, split_type)
        invalid_cases: list[tuple[str, ShapeT, str]] = [("list", 2, "list"), ("list:paired", [2], "list")]
        for collection_type, shape, split_type in invalid_cases:
            collection = self._collection(collection_type, shape)
            with pytest.raises(exceptions.MessageException):
                subcollections._split_dataset_collection(collection, split_type)
            with pytest.raises(exceptions.MessageException):
                subcollections.split_count(collection, split_type)

    def _assert_job_count(self, incoming, expected: int):
        summary = self._summary(incoming)
        assert summary["reason"] is None
        assert summary["job_count"] == expected
        assert len(self._expand(incoming)) == expected

    def _summary(self, incoming):
        return summarize_meta_expansion(self.trans, self.tool, incoming)

    def _expand(self, incoming):
        expanded, _ = expand_meta_parameters(self.trans, self.tool, copy.deepcopy(incoming), "legacy")
        return expanded

    def _encode(self, id: int) -> str:
        return self.app.security.encode_id(id)

    def _hda(self) -> model.HistoryDatasetAssociation:
        hda = model.HistoryDatasetAssociation(
            history=self.history, extension="txt", create_dataset=True, sa_session=self.session
        )
        hda.dataset.state = model.Dataset.states.OK
        self.session.add(hda)
        self.session.commit()
        return hda

    def _hda_ref(self) -> dict[str, Any]:
        return {"src": "hda", "id": self._encode(self._hda().id)}

    def _hda_batch(self, count: int, linked: bool = True) -> dict[str, Any]:
        return {"batch": True, "linked": linked, "values": [self._hda_ref() for _ in range(count)]}

    def _collection(self, collection_type: str, shape: ShapeT, populated: bool = True) -> model.DatasetCollection:
        collection = model.DatasetCollection(collection_type=collection_type, populated=populated)
        if isinstance(shape, int):
            children: list[Any] = [self._hda() for _ in range(shape)]
        else:
            child_type = collection_type.split(":", 1)[1]
            children = [self._collection(child_type, child_shape) for child_shape in shape]
        for index, child in enumerate(children):
            model.DatasetCollectionElement(
                collection=collection, element=child, element_identifier=f"e{index}", element_index=index
            )
        self.session.add(collection)
        self.session.commit()
        return collection

    def _hdca_batch(
        self,
        collection_type: str,
        shape: ShapeT,
        map_over_type: str | None = None,
        linked: bool = True,
        populated: bool = True,
    ) -> dict[str, Any]:
        hdca = model.HistoryDatasetCollectionAssociation(
            collection=self._collection(collection_type, shape, populated=populated), history=self.history
        )
        self.session.add(hdca)
        self.session.commit()
        value: dict[str, Any] = {"src": "hdca", "id": self._encode(hdca.id)}
        if map_over_type:
            value["map_over_type"] = map_over_type
        return {"batch": True, "linked": linked, "values": [value]}
