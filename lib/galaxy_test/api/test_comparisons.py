from typing import Any
from uuid import uuid4

from requests import Response

from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
    RunJobsSummary,
    skip_without_tool,
    wait_on,
    WorkflowPopulator,
)
from galaxy_test.base.workflow_fixtures import (
    default_file_dataset_input_location,
    WORKFLOW_WITH_DEFAULT_FILE_DATASET_INPUT,
)
from ._framework import ApiTestCase

# no labelled inputs or outputs
WORKFLOW_FORTY_TWO = """
class: GalaxyWorkflow
steps:
  forty_two:
    tool_id: expression_forty_two
"""

WORKFLOW_TWO_CAT = """
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  first_cat:
    tool_id: cat1
    in:
      input1: input1
  second_cat:
    tool_id: cat1
    in:
      input1: first_cat/out_file1
test_data:
  input1: "hello world"
"""

WORKFLOW_MAPPED_CAT = """
class: GalaxyWorkflow
inputs:
  input_list:
    type: collection
    collection_type: list
steps:
  mapped_cat:
    tool_id: cat1
    in:
      input1: input_list
"""

WORKFLOW_LABELLED_IO = """
class: GalaxyWorkflow
inputs:
  input1: data
  min_quality:
    type: int
outputs:
  cat_out:
    outputSource: first_cat/out_file1
steps:
  first_cat:
    tool_id: cat1
    in:
      input1: input1
  forty_two:
    tool_id: expression_forty_two
test_data:
  input1: "hello world"
  min_quality:
    value: 7
    type: raw
"""

WORKFLOW_PAUSE_THEN_CAT = """
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  the_pause:
    type: pause
    in:
      input: input1
  after_pause:
    tool_id: cat1
    in:
      input1: the_pause
"""

# after_pause connects a second input, without a pause
WORKFLOW_AFTER_PAUSE_TWO_INPUTS = """
class: GalaxyWorkflow
inputs:
  input1: data
steps:
  after_pause:
    tool_id: cat1
    in:
      input1: input1
      queries_0|input2: input1
"""

WORKFLOW_MAPPED_FAIL = """
class: GalaxyWorkflow
inputs:
  input_list:
    type: collection
    collection_type: list
steps:
  mapped_fail:
    tool_id: fail_identifier
    state:
      failbool: true
    in:
      input1: input_list
"""

WORKFLOW_MAYBE_CAT = """
class: GalaxyWorkflow
inputs:
  input1: data
  run_cat:
    type: boolean
steps:
  maybe_cat:
    tool_id: cat1
    in:
      input1: input1
      when: run_cat
    when: $(inputs.when)
"""

WORKFLOW_OPTIONAL_INPUT = """
class: GalaxyWorkflow
inputs:
  names:
    type: data
    optional: true
steps:
  pick:
    tool_id: data_optional
    in:
      names: names
"""

WORKFLOW_MAYBE_SUBWORKFLOW = """
class: GalaxyWorkflow
inputs:
  input1: data
  run_inner:
    type: boolean
steps:
  maybe_inner:
    run:
      class: GalaxyWorkflow
      inputs:
        inner_input: data
      outputs:
        inner_out:
          outputSource: inner_cat/out_file1
      steps:
        inner_cat:
          tool_id: cat1
          in:
            input1: inner_input
    in:
      inner_input: input1
      when: run_inner
    when: $(inputs.when)
"""


class TestComparisonsApi(ApiTestCase):
    dataset_populator: DatasetPopulator
    workflow_populator: WorkflowPopulator

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.dataset_collection_populator = DatasetCollectionPopulator(self.galaxy_interactor)
        self.workflow_populator = WorkflowPopulator(self.galaxy_interactor)

    @skip_without_tool("cat1")
    @skip_without_tool("multi_data_param")
    @skip_without_tool("multi_output_assign_primary")
    def test_io_names_probe(self):
        """Pin the job input/output association names that comparison columns normalize."""
        with self.dataset_populator.test_history() as history_id:
            hda1 = {"src": "hda", "id": self.dataset_populator.new_dataset(history_id, content="a\n", wait=True)["id"]}
            hda2 = {"src": "hda", "id": self.dataset_populator.new_dataset(history_id, content="b\n", wait=True)["id"]}

            job = self._run_and_show("cat1", {"input1": hda1, "queries_0|input2": hda2}, history_id)
            assert set(job["inputs"]) == {"input1", "queries_0|input2"}
            assert set(job["outputs"]) == {"out_file1"}

            multi_inputs = {"f1": {"batch": False, "values": [hda1, hda2]}, "f2": hda1}
            job = self._run_and_show("multi_data_param", multi_inputs, history_id)
            # a multiple data param records the first dataset under its name and every dataset under name + index
            assert set(job["inputs"]) == {"f1", "f11", "f12", "f2", "f21"}
            assert job["inputs"]["f1"]["id"] == job["inputs"]["f11"]["id"]
            assert set(job["outputs"]) == {"out1", "out2"}

            job = self._run_and_show("multi_output_assign_primary", {"input": hda1}, history_id)
            assert set(job["outputs"]) == {
                "other",
                "sample",
                "__new_primary_file_sample|sample2__",
                "__new_primary_file_sample|sample3__",
            }

            fetch = self.dataset_collection_populator.create_list_in_history(history_id, wait=True).json()
            hdca_id = fetch["outputs"][0]["id"]
            response = self.dataset_populator.run_tool(
                "cat1", {"input1": {"batch": True, "values": [{"src": "hdca", "id": hdca_id}]}}, history_id
            )
            assert response["implicit_collections"][0]["output_name"] == "out_file1"
            for job_summary in response["jobs"]:
                self.dataset_populator.wait_for_job(job_summary["id"], assert_ok=True)
                job = self.dataset_populator.get_job_details(job_summary["id"], full=True).json()
                assert set(job["inputs"]) == {"input1"}
                assert set(job["outputs"]) == {"out_file1"}
                assert set(job["output_collections"]) == {"out_file1"}

    @skip_without_tool("cat1")
    def test_step_runs_across_versions(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id, invocations=2)
            self._relabel(summary.workflow_id, "first_cat", "first_cat_v1")
            rerun_id = self._rerun(summary)

            response = self._step_runs(summary.workflow_id, "second_cat")
            assert response.headers["total_matches"] == "3"
            table = response.json()
            rows = table["rows"]
            assert [row["version"] for row in rows] == [1, 0, 0]
            invocation_ids = [row["run"]["id"] for row in rows]
            assert invocation_ids[:2] == [rerun_id, summary.invocation_id]
            assert all(row["run"]["model"] == "WorkflowInvocation" for row in rows)
            assert table["query"]["kind"] == "step_runs"
            assert table["query"]["workflow_id"] == summary.workflow_id
            assert table["query"]["step_label"] == "second_cat"

            assert [c["key"] for c in table["columns"]] == ["input:input1", "output:out_file1"]
            assert [c["role"] for c in table["columns"]] == ["input", "output"]
            for row in rows:
                assert row["state"] == "ok"
                assert row["reused"] == "no"
                assert row["step_job"]["model"] == "Job"
                assert row["tool_version"] == "1.0.0"
                assert row["history"]["id"] == history_id
                assert row["tool_id"] == "cat1"
                assert set(row["cells"]) == {"input:input1", "output:out_file1"}
                for cell in row["cells"].values():
                    details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=cell["id"])
                    assert cell["type"] == "dataset"
                    assert (cell["hid"], cell["name"]) == (details["hid"], details["name"])
                    assert cell["extension"] == "txt"
                    assert cell["state"] == "ok"
                    assert cell["history_id"] == history_id
                    assert cell["metadata"] == {}
            # each run's output is its own dataset
            assert len({row["cells"]["output:out_file1"]["id"] for row in rows}) == 3

            # paging keeps the total
            response = self._step_runs(summary.workflow_id, "second_cat", limit=1, offset=1)
            assert response.headers["total_matches"] == "3"
            assert [row["run"]["id"] for row in response.json()["rows"]] == invocation_ids[1:2]

            # oldest first
            ascending = self._step_runs_table(summary.workflow_id, "second_cat", sort_desc=False)
            assert [row["run"]["id"] for row in ascending["rows"]] == invocation_ids[::-1]

            # states filter on the step's job state
            assert len(self._step_runs_table(summary.workflow_id, "second_cat", states="ok")["rows"]) == 3
            response = self._step_runs(summary.workflow_id, "second_cat", states="error")
            assert response.headers["total_matches"] == "0"
            assert response.json()["rows"] == []

            # versions filter, 0-based, repeated for several
            assert table["versions_available"] == [0, 1]
            response = self._step_runs(summary.workflow_id, "second_cat", versions=1)
            assert response.headers["total_matches"] == "1"
            assert [row["run"]["id"] for row in response.json()["rows"]] == [rerun_id]
            assert response.json()["query"]["versions"] == [1]
            both = self._step_runs(summary.workflow_id, "second_cat", versions=[0, 1])
            assert both.headers["total_matches"] == "3"
            # a version without the step matches nothing, but the step's versions are still offered
            absent = self._step_runs(summary.workflow_id, "second_cat", versions=7)
            assert absent.headers["total_matches"] == "0"
            assert (absent.json()["rows"], absent.json()["versions_available"]) == ([], [0, 1])
            self._step_runs(summary.workflow_id, "second_cat", expected_status=400, versions="v1")

            # metadata elements
            table = self._step_runs_table(summary.workflow_id, "second_cat", metadata_elements="data_lines")
            output_column = next(c for c in table["columns"] if c["key"] == "output:out_file1")
            assert "data_lines" in output_column["metadata_keys"]
            assert table["rows"][0]["cells"]["output:out_file1"]["metadata"] == {"data_lines": 1}

            # instance=true takes the invocation's Workflow id
            invocation = self.workflow_populator.get_invocation(invocation_ids[0])
            by_instance = self._step_runs_table(invocation["workflow_id"], "second_cat", instance=True)
            assert by_instance["query"]["workflow_id"] == summary.workflow_id
            assert [row["run"]["id"] for row in by_instance["rows"]] == invocation_ids

    @skip_without_tool("cat1")
    def test_step_runs_after_workflow_rename(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
            self._refactor(summary.workflow_id, {"action_type": "update_name", "name": "renamed workflow"})
            self._rerun(summary)
            table = self._step_runs_table(summary.workflow_id, "first_cat")
            assert len(table["rows"]) == 2

    @skip_without_tool("cat1")
    def test_versions_available_lists_invoked_versions(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
            self._refactor(summary.workflow_id, {"action_type": "update_name", "name": "renamed workflow"})
            assert self._step_runs_table(summary.workflow_id, "second_cat")["versions_available"] == [0]
            assert self._output_runs_table(summary.workflow_id)["versions_available"] == [0]
            self._rerun(summary)
            assert self._step_runs_table(summary.workflow_id, "second_cat")["versions_available"] == [0, 1]
            assert self._output_runs_table(summary.workflow_id)["versions_available"] == [0, 1]

    @skip_without_tool("cat1")
    def test_step_runs_label_change(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
            self._relabel(summary.workflow_id, "second_cat", "second_cat_renamed")
            new_invocation_id = self._rerun(summary)

            old_table = self._step_runs_table(summary.workflow_id, "second_cat")
            assert [(row["run"]["id"], row["version"]) for row in old_table["rows"]] == [(summary.invocation_id, 0)]
            assert old_table["versions_available"] == [0]
            new_table = self._step_runs_table(summary.workflow_id, "second_cat_renamed")
            assert [(row["run"]["id"], row["version"]) for row in new_table["rows"]] == [(new_invocation_id, 1)]
            assert new_table["versions_available"] == [1]

    @skip_without_tool("cat1")
    def test_step_runs_errors(self):
        workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_TWO_CAT)
        self._step_runs(workflow_id, "", expected_status=400)
        self._step_runs(workflow_id, "not_a_label", expected_status=404)
        self._step_runs(workflow_id, "first_cat", expected_status=400, metadata_elements="bad-name")

    @skip_without_tool("cat1")
    def test_step_runs_owner_filter(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
            self.workflow_populator.make_public(summary.workflow_id)
            with self._different_user():
                with self.dataset_populator.test_history() as other_history_id:
                    other_input = self.dataset_populator.new_dataset(other_history_id, content="other", wait=True)
                    for _ in range(2):
                        self._invoke_and_wait(summary.workflow_id, other_history_id, {"input1": _hda(other_input)})
                    response = self._step_runs(summary.workflow_id, "first_cat")
                    assert response.headers["total_matches"] == "2"
                    rows = response.json()["rows"]
                    assert {row["history"]["id"] for row in rows} == {other_history_id}

            response = self._step_runs(summary.workflow_id, "first_cat")
            assert response.headers["total_matches"] == "1"
            assert [row["run"]["id"] for row in response.json()["rows"]] == [summary.invocation_id]

            with self._different_user(anon=True):
                response = self._step_runs(summary.workflow_id, "first_cat")
                assert response.headers["total_matches"] == "0"
                assert response.json()["rows"] == []

    @skip_without_tool("cat1")
    def test_step_runs_hides_inaccessible_items(self):
        other_email = f"{uuid4()}@example.org"
        with self.dataset_populator.test_history() as owner_history_id:
            owner_dataset = self.dataset_populator.new_dataset(owner_history_id, content="shared\n", wait=True)
            self.dataset_populator.make_public(owner_history_id)
            with self._different_user(other_email):
                with self.dataset_populator.test_history() as history_id:
                    workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_TWO_CAT)
                    self._invoke_and_wait(workflow_id, history_id, {"input1": _hda(owner_dataset)})
                    (row,) = self._step_runs_table(workflow_id, "first_cat")["rows"]
                    # the invocation copies the input into this history; permissions stay on the shared dataset
                    input_cell = row["cells"]["input:input1"]
                    assert (input_cell["type"], input_cell["history_id"]) == ("dataset", history_id)
                    assert input_cell["id"] != owner_dataset["id"]
            self.dataset_populator.make_private(owner_history_id, owner_dataset["id"])
            with self._different_user(other_email):
                (row,) = self._step_runs_table(workflow_id, "first_cat")["rows"]
                assert row["cells"]["input:input1"] == {"type": "missing", "reason": "inaccessible"}
                output_cell = row["cells"]["output:out_file1"]
                assert output_cell["type"] == "dataset"
                assert output_cell["history_id"] == history_id

    @skip_without_tool("cat1")
    def test_step_runs_deleted_history(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
        with self.dataset_populator.test_history() as second_history_id:
            second_input = self.dataset_populator.new_dataset(second_history_id, content="second", wait=True)
            self._invoke_and_wait(summary.workflow_id, second_history_id, {"input1": _hda(second_input)})
            self.dataset_populator.delete_history(history_id)
            rows = self._step_runs_table(summary.workflow_id, "first_cat")["rows"]
            assert [(row["history"]["id"], row["history"]["deleted"]) for row in rows] == [
                (second_history_id, False),
                (history_id, True),
            ]

    @skip_without_tool("cat1")
    def test_step_runs_cached_job(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self._run_two_cat(history_id)
            self._rerun(summary, use_cached_job=True)
            rows = self._step_runs_table(summary.workflow_id, "first_cat")["rows"]
            assert [row["reused"] for row in rows] == ["yes", "no"]

    @skip_without_tool("cat1")
    def test_step_runs_mapped_step(self):
        with self.dataset_populator.test_history() as history_id:
            hdas = [self.dataset_populator.new_dataset(history_id, content=f"line {i}\n", wait=True) for i in range(3)]
            identifiers = [{"name": f"el{i}", "src": "hda", "id": hda["id"]} for i, hda in enumerate(hdas)]
            two_list = self._list_from(history_id, identifiers[:2])
            three_list = self._list_from(history_id, identifiers)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_MAPPED_CAT)
            self._invoke_and_wait(workflow_id, history_id, {"input_list": {"src": "hdca", "id": two_list}})
            self._invoke_and_wait(
                workflow_id, history_id, {"input_list": {"src": "hdca", "id": three_list}}, use_cached_job=True
            )

            table = self._step_runs_table(workflow_id, "mapped_cat")
            assert [c["key"] for c in table["columns"]] == ["input:input1", "output:out_file1"]
            superset_row, first_row = table["rows"]
            assert first_row["step_job"]["model"] == "ImplicitCollectionJobs"
            assert first_row["step_job"]["job_count"] == 2
            assert first_row["step_job"]["states"] == {"ok": 2}
            assert first_row["state"] == "ok"
            assert first_row["reused"] == "no"
            assert first_row["cells"]["input:input1"]["type"] == "collection"
            assert first_row["cells"]["input:input1"]["id"] == two_list
            output_cell = first_row["cells"]["output:out_file1"]
            assert output_cell["type"] == "collection"
            assert output_cell["collection_type"] == "list"
            assert output_cell["element_count"] == 2
            assert superset_row["step_job"]["job_count"] == 3
            assert superset_row["cells"]["input:input1"]["id"] == three_list
            assert superset_row["reused"] == "partial"

    @skip_without_tool("cat1")
    def test_step_runs_not_run_yet(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="paused\n", wait=True)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_PAUSE_THEN_CAT)
            inputs = {"input1": _hda(hda)}
            resumed_id = self.workflow_populator.invoke_workflow_and_assert_ok(
                workflow_id, history_id, inputs, inputs_by="name"
            )
            pause_step = wait_on(lambda: self._invocation_step(resumed_id, order_index=1), "pause step scheduled")
            response = self._put(f"invocations/{resumed_id}/steps/{pause_step['id']}", {"action": True}, json=True)
            self._assert_status_code_is_ok(response)
            self.workflow_populator.wait_for_invocation_and_jobs(history_id, workflow_id, resumed_id)
            # the paused run is the only row of its version
            self._refactor(workflow_id, {"action_type": "update_name", "name": "paused version"})
            paused_id = self.workflow_populator.invoke_workflow_and_assert_ok(
                workflow_id, history_id, inputs, inputs_by="name"
            )

            response = self._step_runs(workflow_id, "after_pause")
            assert response.headers["total_matches"] == "2"
            paused_row, resumed_row = response.json()["rows"]
            assert resumed_row["run"]["id"] == resumed_id
            assert {cell["type"] for cell in resumed_row["cells"].values()} == {"dataset"}
            assert paused_row["run"]["id"] == paused_id
            assert (paused_row["version"], resumed_row["version"]) == (1, 0)
            assert paused_row["state"] == "new"
            assert paused_row["step_job"] is None
            assert paused_row["cells"] == {
                "input:input1": {"type": "missing", "reason": "not_run_yet"},
                "output:out_file1": {"type": "missing", "reason": "not_run_yet"},
            }
            ok_rows = self._step_runs_table(workflow_id, "after_pause", states="ok")["rows"]
            assert [row["run"]["id"] for row in ok_rows] == [resumed_id]
            new_rows = self._step_runs_table(workflow_id, "after_pause", states="new")["rows"]
            assert [row["run"]["id"] for row in new_rows] == [paused_id]

            # a pause step has no job and is "scheduled" both while paused and once resumed; its action differs
            wait_on(lambda: self._invocation_step(paused_id, order_index=1), "pause step reached")
            pause_rows = {row["run"]["id"]: row for row in self._step_runs_table(workflow_id, "the_pause")["rows"]}
            pause_fields = ("state", "step_job", "step_type", "step_action")
            assert {
                run_id: (row["run"]["state"], *(row[f] for f in pause_fields)) for run_id, row in pause_rows.items()
            } == {
                resumed_id: ("completed", "scheduled", None, "pause", True),
                paused_id: ("ready", "scheduled", None, "pause", None),
            }
            assert (paused_row["step_type"], paused_row["step_action"]) == ("tool", None)

    @skip_without_tool("cat1")
    def test_step_runs_not_run_yet_reads_its_version_inputs(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="paused\n", wait=True)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_PAUSE_THEN_CAT)
            inputs = {"input1": _hda(hda)}
            paused_id = self.workflow_populator.invoke_workflow_and_assert_ok(
                workflow_id, history_id, inputs, inputs_by="name"
            )
            wait_on(lambda: self._invocation_step(paused_id, order_index=1), "pause step reached")
            second_version_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_AFTER_PAUSE_TWO_INPUTS)
            second_version = self.workflow_populator.download_workflow(second_version_id)
            self._assert_status_code_is_ok(self.workflow_populator.update_workflow(workflow_id, second_version))
            ran_id = self._invoke_and_wait(workflow_id, history_id, inputs)

            table = self._step_runs_table(workflow_id, "after_pause")
            assert [column["key"] for column in table["columns"]] == [
                "input:input1",
                "input:queries_0|input2",
                "output:out_file1",
            ]
            assert [column["present_in_versions"] for column in table["columns"]] == [None, [1], None]
            ran_row, paused_row = table["rows"]
            assert (paused_row["state"], paused_row["step_job"]) == ("new", None)
            assert [row["run"]["id"] for row in (ran_row, paused_row)] == [ran_id, paused_id]
            assert ran_row["cells"]["input:queries_0|input2"]["id"] == hda["id"]
            # version 0's step doesn't connect queries_0|input2
            assert paused_row["cells"] == {
                "input:input1": {"type": "missing", "reason": "not_run_yet"},
                "input:queries_0|input2": {"type": "missing", "reason": "not_in_version"},
                "output:out_file1": {"type": "missing", "reason": "not_run_yet"},
            }

    @skip_without_tool("cat1")
    def test_step_runs_mapped_over_empty_list(self):
        with self.dataset_populator.test_history() as history_id:
            empty_list = self._list_from(history_id, [])
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_MAPPED_CAT)
            self._invoke_and_wait(workflow_id, history_id, {"input_list": {"src": "hdca", "id": empty_list}})
            (row,) = self._step_runs_table(workflow_id, "mapped_cat")["rows"]
            step_job = row["step_job"]
            assert step_job["model"] == "ImplicitCollectionJobs"
            assert step_job["populated_state"] == "ok"
            assert step_job["job_count"] == 0
            assert step_job["states"] == {}
            assert step_job["representative_job_id"] is None
            assert row["state"] == "ok"
            assert row["reused"] is None
            assert row["cells"]["input:input1"]["id"] == empty_list
            assert row["cells"]["output:out_file1"]["element_count"] == 0
            # the state filter matches the shown state
            ok_rows = self._step_runs_table(workflow_id, "mapped_cat", states="ok")["rows"]
            assert [ok_row["run"]["id"] for ok_row in ok_rows] == [row["run"]["id"]]
            assert self._step_runs(workflow_id, "mapped_cat", states="new").headers["total_matches"] == "0"

    @skip_without_tool("cat1")
    @skip_without_tool("expression_forty_two")
    def test_step_runs_input_steps(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self.workflow_populator.run_workflow(WORKFLOW_LABELLED_IO, history_id=history_id)
            hda = self.dataset_populator.new_dataset(history_id, content="other\n", wait=True)
            rerun_id = self._invoke_and_wait(summary.workflow_id, history_id, {"input1": _hda(hda), "min_quality": 9})

            table = self._step_runs_table(summary.workflow_id, "min_quality")
            assert [(column["key"], column["role"]) for column in table["columns"]] == [
                ("parameter:min_quality", "parameter")
            ]
            assert [row["run"]["id"] for row in table["rows"]] == [rerun_id, summary.invocation_id]
            assert [row["cells"]["parameter:min_quality"]["value"] for row in table["rows"]] == [9, 7]

            # a data input step shows its dataset once, as an input
            data_table = self._step_runs_table(summary.workflow_id, "input1")
            assert [(column["key"], column["role"]) for column in data_table["columns"]] == [("input:input1", "input")]
            assert [row["cells"]["input:input1"]["id"] for row in data_table["rows"]] == [
                hda["id"],
                summary.inputs["input1"]["id"],
            ]

    @skip_without_tool("cat1")
    def test_step_runs_defaulted_data_input(self, test_http_server):
        with self.dataset_populator.test_history() as history_id:
            workflow = WORKFLOW_WITH_DEFAULT_FILE_DATASET_INPUT.format(
                location=default_file_dataset_input_location(test_http_server)
            )
            summary = self.workflow_populator.run_workflow(workflow, history_id=history_id)
            invocation = self.workflow_populator.get_invocation(summary.invocation_id, step_details=True)
            default_id = invocation["steps"][0]["outputs"]["output"]["id"]

            table = self._step_runs_table(summary.workflow_id, "default_file_input")
            assert [(column["key"], column["role"]) for column in table["columns"]] == [
                ("input:default_file_input", "input")
            ]
            (row,) = table["rows"]
            cell = row["cells"]["input:default_file_input"]
            assert (cell["type"], cell["id"]) == ("dataset", default_id)

    @skip_without_tool("cat1")
    def test_step_runs_skipped_step(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="maybe\n", wait=True)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_MAYBE_CAT)
            skipped_id = self._invoke_and_wait(workflow_id, history_id, {"input1": _hda(hda), "run_cat": False})
            self._refactor(workflow_id, {"action_type": "update_name", "name": "second version"})
            ran_id = self._invoke_and_wait(workflow_id, history_id, {"input1": _hda(hda), "run_cat": True})

            ran_row, skipped_row = self._step_runs_table(workflow_id, "maybe_cat")["rows"]
            assert (ran_row["run"]["id"], ran_row["version"]) == (ran_id, 1)
            assert (skipped_row["run"]["id"], skipped_row["version"]) == (skipped_id, 0)
            assert skipped_row["state"] == skipped_row["step_job"]["state"] == "skipped"
            assert skipped_row["cells"]["input:input1"]["id"] == hda["id"]
            # a skipped job records null placeholder outputs; they show as skipped, in the version
            assert skipped_row["cells"]["output:out_file1"] == {"type": "missing", "reason": "skipped"}
            assert ran_row["cells"]["output:out_file1"]["type"] == "dataset"
            for inline in (True, False):
                table = self._step_runs_table(workflow_id, "maybe_cat", inline_expression_values=inline)
                assert table["rows"][1]["cells"]["output:out_file1"] == {"type": "missing", "reason": "skipped"}

            tool_rows = self._tool_runs_table("cat1", history_id=history_id)["rows"]
            (skipped_tool_row,) = [row for row in tool_rows if row["state"] == "skipped"]
            assert skipped_tool_row["cells"]["output:out_file1"] == {"type": "missing", "reason": "skipped"}

    @skip_without_tool("data_optional")
    def test_step_runs_unsupplied_optional_input_is_in_version(self):
        with self.dataset_populator.test_history() as history_id:
            names = self.dataset_populator.new_dataset(
                history_id, content="a\ta\n", file_type="mothur.names", wait=True
            )
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_OPTIONAL_INPUT)
            without_id = self._invoke_and_wait(workflow_id, history_id, {})
            self._refactor(workflow_id, {"action_type": "update_name", "name": "second version"})
            with_id = self._invoke_and_wait(workflow_id, history_id, {"names": _hda(names)})

            with_row, without_row = self._step_runs_table(workflow_id, "pick")["rows"]
            assert [(row["run"]["id"], row["version"]) for row in (with_row, without_row)] == [
                (with_id, 1),
                (without_id, 0),
            ]
            assert with_row["cells"]["input:names"]["id"] == names["id"]
            # version 0 connects the input too; this run just didn't supply it
            assert without_row["cells"]["input:names"] == {"type": "missing", "reason": "no_output"}

    @skip_without_tool("cat1")
    def test_step_runs_skipped_subworkflow_step(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="inner\n", wait=True)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_MAYBE_SUBWORKFLOW)
            inputs = {"input1": _hda(hda)}
            skipped_id = self._invoke_and_wait(workflow_id, history_id, {**inputs, "run_inner": False})
            self._refactor(workflow_id, {"action_type": "update_name", "name": "second version"})
            ran_id = self._invoke_and_wait(workflow_id, history_id, {**inputs, "run_inner": True})

            table = self._step_runs_table(workflow_id, "maybe_inner")
            ran_row, skipped_row = table["rows"]
            assert [(row["run"]["id"], row["version"]) for row in (ran_row, skipped_row)] == [
                (ran_id, 1),
                (skipped_id, 0),
            ]
            assert [column["key"] for column in table["columns"]] == ["output:inner_out"]
            assert table["columns"][0]["present_in_versions"] is None
            assert ran_row["cells"]["output:inner_out"]["type"] == "dataset"
            # the subworkflow still runs, its skipped inner step recording a null placeholder
            skipped_cell = skipped_row["cells"]["output:inner_out"]
            assert (skipped_cell["type"], skipped_cell["value"], skipped_cell["source"]) == (
                "value",
                None,
                "expression_json",
            )

    @skip_without_tool("multi_data_param")
    def test_tool_runs_multiple_data_input(self):
        with self.dataset_populator.test_history() as history_id:
            hdas = [self.dataset_populator.new_dataset(history_id, content=f"{i}\n", wait=True) for i in range(3)]
            inputs = {"f1": {"batch": False, "values": [_hda(hda) for hda in hdas]}, "f2": _hda(hdas[0])}
            self._run_and_show("multi_data_param", inputs, history_id)
            list_id = self._list_from(
                history_id, [{"name": f"el{i}", "src": "hda", "id": hda["id"]} for i, hda in enumerate(hdas[:2])]
            )
            # a reduced collection records its elements as f11, f12... too
            self._run_and_show(
                "multi_data_param", {"f1": {"src": "hdca", "id": list_id}, "f2": _hda(hdas[0])}, history_id
            )

            table = self._tool_runs_table("multi_data_param", history_id=history_id)
            assert [column["key"] for column in table["columns"]] == [
                "input:f1",
                "input:f2",
                "output:out1",
                "output:out2",
            ]
            reduced_row, row = table["rows"]
            f1 = row["cells"]["input:f1"]
            assert f1["type"] == "dataset_list"
            assert [(item["type"], item["id"]) for item in f1["items"]] == [("dataset", hda["id"]) for hda in hdas]
            # one dataset stays a plain cell
            assert (row["cells"]["input:f2"]["type"], row["cells"]["input:f2"]["id"]) == ("dataset", hdas[0]["id"])
            assert (reduced_row["cells"]["input:f1"]["type"], reduced_row["cells"]["input:f1"]["id"]) == (
                "collection",
                list_id,
            )

    @skip_without_tool("fail_identifier")
    def test_runs_state_filter_matches_mapped_batch_state(self):
        with self.dataset_populator.test_history() as history_id:
            hdas = [self.dataset_populator.new_dataset(history_id, content=f"{i}\n", wait=True) for i in range(2)]
            identifiers = [{"name": name, "src": "hda", "id": hda["id"]} for name, hda in zip(("fail", "pass"), hdas)]
            list_id = self._list_from(history_id, identifiers)
            workflow_id = self.workflow_populator.upload_yaml_workflow(WORKFLOW_MAPPED_FAIL)
            self._invoke_and_wait(
                workflow_id, history_id, {"input_list": {"src": "hdca", "id": list_id}}, assert_ok=False
            )

            (row,) = self._step_runs_table(workflow_id, "mapped_fail", states="error")["rows"]
            assert row["step_job"]["model"] == "ImplicitCollectionJobs"
            assert row["step_job"]["states"] == {"ok": 1, "error": 1}
            assert row["state"] == "error"
            (tool_row,) = self._tool_runs_table("fail_identifier", history_id=history_id, states="error")["rows"]
            assert tool_row["run"]["model"] == "ImplicitCollectionJobs"
            assert tool_row["run"]["states"] == {"ok": 1, "error": 1}
            assert tool_row["state"] == "error"
            assert tool_row["via"]["step_label"] == "mapped_fail"
            # an ok member doesn't make the error batch match ok
            for state in ("ok", "running"):
                assert self._step_runs(workflow_id, "mapped_fail", states=state).headers["total_matches"] == "0"
                tool_runs = self._tool_runs("fail_identifier", history_id=history_id, states=state)
                assert tool_runs.headers["total_matches"] == "0"
            # a mapped workflow step is a workflow job too
            without = self._tool_runs("fail_identifier", history_id=history_id, include_workflow_jobs=False)
            assert without.headers["total_matches"] == "0"

    @skip_without_tool("cat1")
    @skip_without_tool("expression_forty_two")
    def test_output_runs_across_versions(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self.workflow_populator.run_workflow(WORKFLOW_LABELLED_IO, history_id=history_id)
            self._add_workflow_output(summary.workflow_id, "forty_two", "out1", "n")
            rerun_id = self._rerun(summary)
            for invocation_id in (summary.invocation_id, rerun_id):
                self.workflow_populator.wait_for_invocation_and_completion(invocation_id)

            response = self._output_runs(summary.workflow_id)
            assert response.headers["total_matches"] == "2"
            table = response.json()
            assert table["query"]["kind"] == "output_runs"
            assert table["query"]["workflow_id"] == summary.workflow_id
            columns = {column["key"]: column for column in table["columns"]}
            # step order; format2 import orders forty_two (no inputs) before first_cat
            assert list(columns) == ["input:input1", "parameter:min_quality", "output:n", "output:cat_out"]
            assert [column["role"] for column in columns.values()] == ["input", "parameter", "output", "output"]
            assert columns["output:n"]["present_in_versions"] == [1]
            assert columns["output:cat_out"]["present_in_versions"] is None
            assert not any(column["duplicate"] for column in columns.values())
            assert table["output_labels_available"] == ["n", "cat_out"]
            assert table["tool_versions_available"] is None

            new_row, old_row = table["rows"]
            assert [(row["run"]["id"], row["version"]) for row in (new_row, old_row)] == [
                (rerun_id, 1),
                (summary.invocation_id, 0),
            ]
            for row in (new_row, old_row):
                assert row["run"]["model"] == "WorkflowInvocation"
                assert row["state"] == row["run"]["state"] == "completed"
                assert row["reused"] is None
                assert row["step_job"] is None
                assert row["cells"]["parameter:min_quality"] == {
                    "type": "value",
                    "value": 7,
                    "source": "parameter",
                    "dataset_id": None,
                }
                for key in ("input:input1", "output:cat_out"):
                    cell = row["cells"][key]
                    details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=cell["id"])
                    assert cell["type"] == "dataset"
                    assert (cell["hid"], cell["name"]) == (details["hid"], details["name"])
            assert old_row["cells"]["output:n"] == {"type": "missing", "reason": "not_in_version"}
            n_cell = new_row["cells"]["output:n"]
            assert (n_cell["type"], n_cell["value"], n_cell["source"]) == ("value", 42, "expression_json")
            n_details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=n_cell["dataset_id"])
            assert n_details["extension"] == "expression.json"

            # expression values as datasets
            raw = self._output_runs_table(summary.workflow_id, inline_expression_values=False)
            n_dataset = raw["rows"][0]["cells"]["output:n"]
            assert (n_dataset["type"], n_dataset["id"], n_dataset["extension"]) == (
                "dataset",
                n_cell["dataset_id"],
                "expression.json",
            )

            # output_labels filters output columns only
            filtered = self._output_runs_table(summary.workflow_id, output_labels=["n"])
            filtered_keys = ["input:input1", "parameter:min_quality", "output:n"]
            assert [column["key"] for column in filtered["columns"]] == filtered_keys
            assert [set(row["cells"]) for row in filtered["rows"]] == [set(filtered_keys)] * 2
            assert filtered["output_labels_available"] == ["n", "cat_out"]

            # the facet covers versions off the page
            oldest = self._output_runs_table(summary.workflow_id, limit=1, sort_desc=False)
            assert [row["version"] for row in oldest["rows"]] == [0]
            assert oldest["output_labels_available"] == ["n", "cat_out"]

            # states filter on the invocation state
            assert len(self._output_runs_table(summary.workflow_id, states="completed")["rows"]) == 2
            response = self._output_runs(summary.workflow_id, states="failed")
            assert response.headers["total_matches"] == "0"

            # versions filter, 0-based, repeated for several
            assert table["versions_available"] == [0, 1]
            response = self._output_runs(summary.workflow_id, versions=0)
            assert response.headers["total_matches"] == "1"
            old_only = response.json()
            assert [row["run"]["id"] for row in old_only["rows"]] == [summary.invocation_id]
            assert old_only["query"]["versions"] == [0]
            assert old_only["versions_available"] == [0, 1]
            assert self._output_runs(summary.workflow_id, versions=[0, 1]).headers["total_matches"] == "2"
            absent = self._output_runs(summary.workflow_id, versions=7)
            assert absent.headers["total_matches"] == "0"
            assert (absent.json()["rows"], absent.json()["versions_available"]) == ([], [0, 1])
            self._output_runs(summary.workflow_id, expected_status=400, versions="v1")

    @skip_without_tool("expression_forty_two")
    def test_output_runs_version_without_labelled_io(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self.workflow_populator.run_workflow(WORKFLOW_FORTY_TWO, history_id=history_id)
            self._add_workflow_output(summary.workflow_id, "forty_two", "out1", "n")
            self._rerun(summary)

            table = self._output_runs_table(summary.workflow_id)
            assert [(column["key"], column["present_in_versions"]) for column in table["columns"]] == [
                ("output:n", [1])
            ]
            assert [row["version"] for row in table["rows"]] == [1, 0]
            assert table["rows"][1]["cells"]["output:n"] == {"type": "missing", "reason": "not_in_version"}

    @skip_without_tool("cat1")
    @skip_without_tool("expression_forty_two")
    def test_output_runs_owner_filter(self):
        with self.dataset_populator.test_history() as history_id:
            summary = self.workflow_populator.run_workflow(WORKFLOW_LABELLED_IO, history_id=history_id)
            self.workflow_populator.make_public(summary.workflow_id)
            with self._different_user():
                response = self._output_runs(summary.workflow_id)
                assert response.headers["total_matches"] == "0"
                assert response.json()["rows"] == []
            with self._different_user(anon=True):
                assert self._output_runs(summary.workflow_id).headers["total_matches"] == "0"
            response = self._output_runs(summary.workflow_id)
            assert response.headers["total_matches"] == "1"
            assert [row["run"]["id"] for row in response.json()["rows"]] == [summary.invocation_id]

    @skip_without_tool("multiple_versions")
    def test_tool_runs_across_versions(self):
        with self._different_user(f"{uuid4()}@example.org"):
            with self.dataset_populator.test_history() as history_id:
                job_ids = {}
                for tool_version in ("0.2", "0.1", "0.1+galaxy6"):
                    response = self.dataset_populator.run_tool(
                        "multiple_versions", {"inttest": 3}, history_id, tool_version=tool_version
                    )
                    job_ids[tool_version] = response["jobs"][0]["id"]
                    self.dataset_populator.wait_for_job(job_ids[tool_version], assert_ok=True)

                response = self._tool_runs("multiple_versions")
                assert response.headers["total_matches"] == "3"
                table = response.json()
                assert table["query"]["kind"] == "tool_runs"
                assert table["tool_versions_available"] == ["0.1", "0.1+galaxy6", "0.2"]
                assert [c["key"] for c in table["columns"]] == ["output:out_file1"]
                rows = table["rows"]
                assert [row["run"]["id"] for row in rows] == [job_ids[v] for v in ("0.1+galaxy6", "0.1", "0.2")]
                for row, tool_version in zip(rows, ("0.1+galaxy6", "0.1", "0.2")):
                    assert row["run"]["model"] == "Job"
                    assert (row["tool_id"], row["tool_version"]) == ("multiple_versions", tool_version)
                    assert (row["state"], row["run"]["state"]) == ("ok", "ok")
                    assert row["reused"] == "no"
                    assert row["via"] is None
                    assert row["version"] is None
                    assert row["history"]["id"] == history_id
                    cell = row["cells"]["output:out_file1"]
                    details = self.dataset_populator.get_history_dataset_details(history_id, dataset_id=cell["id"])
                    assert (cell["type"], cell["hid"], cell["name"]) == ("dataset", details["hid"], details["name"])

                filtered = self._tool_runs("multiple_versions", tool_versions="0.1")
                assert filtered.headers["total_matches"] == "1"
                assert [row["run"]["id"] for row in filtered.json()["rows"]] == [job_ids["0.1"]]
                # the facet ignores the version filter
                assert filtered.json()["tool_versions_available"] == ["0.1", "0.1+galaxy6", "0.2"]
                assert self._tool_runs("multiple_versions", tool_versions="9.9").headers["total_matches"] == "0"

    @skip_without_tool("cat1")
    def test_tool_runs_mapped_batch_is_one_row(self):
        with self._different_user(f"{uuid4()}@example.org"):
            with self.dataset_populator.test_history() as history_id:
                hdas = [self.dataset_populator.new_dataset(history_id, content=f"{i}\n", wait=True) for i in range(3)]
                identifiers = [{"name": f"el{i}", "src": "hda", "id": hda["id"]} for i, hda in enumerate(hdas)]
                list_id = self._list_from(history_id, identifiers)
                mapped = self.dataset_populator.run_tool(
                    "cat1", {"input1": {"batch": True, "values": [{"src": "hdca", "id": list_id}]}}, history_id
                )
                for job in mapped["jobs"]:
                    self.dataset_populator.wait_for_job(job["id"], assert_ok=True)
                plain = self.dataset_populator.run_tool(
                    "cat1", {"input1": {"src": "hda", "id": hdas[0]["id"]}}, history_id
                )
                self.dataset_populator.wait_for_job(plain["jobs"][0]["id"], assert_ok=True)

                response = self._tool_runs("cat1", history_id=history_id)
                assert response.headers["total_matches"] == "2"
                table = response.json()
                assert [c["key"] for c in table["columns"]] == ["input:input1", "output:out_file1"]
                plain_row, mapped_row = table["rows"]
                assert plain_row["run"] == {"model": "Job", "id": plain["jobs"][0]["id"], "state": "ok"}
                assert plain_row["cells"]["input:input1"]["id"] == hdas[0]["id"]
                assert plain_row["cells"]["output:out_file1"]["id"] == plain["outputs"][0]["id"]
                run = mapped_row["run"]
                assert run["model"] == "ImplicitCollectionJobs"
                assert run["id"] == mapped["implicit_collections"][0]["implicit_collection_jobs_id"]
                assert (run["job_count"], run["states"], run["populated_state"]) == (3, {"ok": 3}, "ok")
                assert run["representative_job_id"] == mapped["jobs"][0]["id"]
                assert mapped_row["state"] == "ok"
                assert mapped_row["cells"]["input:input1"]["id"] == list_id
                output_cell = mapped_row["cells"]["output:out_file1"]
                assert output_cell["id"] == mapped["implicit_collections"][0]["id"]
                assert (output_cell["type"], output_cell["element_count"]) == ("collection", 3)

                # a batch matches a state filter when any member job does
                assert self._tool_runs("cat1", history_id=history_id, states="ok").headers["total_matches"] == "2"
                assert self._tool_runs("cat1", history_id=history_id, states="error").headers["total_matches"] == "0"

    @skip_without_tool("cat1")
    def test_tool_runs_workflow_jobs(self):
        with self._different_user(f"{uuid4()}@example.org"):
            with self.dataset_populator.test_history() as history_id:
                summary = self._run_two_cat(history_id)
                hda = self.dataset_populator.new_dataset(history_id, content="plain\n", wait=True)
                plain = self.dataset_populator.run_tool("cat1", {"input1": {"src": "hda", "id": hda["id"]}}, history_id)
                self.dataset_populator.wait_for_job(plain["jobs"][0]["id"], assert_ok=True)

                rows = self._tool_runs_table("cat1", history_id=history_id)["rows"]
                assert len(rows) == 3
                assert rows[0]["via"] is None
                vias = [row["via"] for row in rows[1:]]
                assert {via["invocation_id"] for via in vias} == {summary.invocation_id}
                assert sorted(via["step_label"] for via in vias) == ["first_cat", "second_cat"]

                without = self._tool_runs("cat1", history_id=history_id, include_workflow_jobs=False)
                assert without.headers["total_matches"] == "1"
                assert [row["run"]["id"] for row in without.json()["rows"]] == [plain["jobs"][0]["id"]]

    @skip_without_tool("cat1")
    def test_tool_runs_owner_filter_and_access(self):
        with self.dataset_populator.test_history() as owner_history_id:
            list_id = self.dataset_collection_populator.create_list_in_history(owner_history_id, wait=True).json()[
                "outputs"
            ][0]["id"]
            self.dataset_populator.make_public(owner_history_id)
            self.dataset_populator.run_tool(
                "cat1", {"input1": {"batch": True, "values": [{"src": "hdca", "id": list_id}]}}, owner_history_id
            )
            assert self._tool_runs("cat1", history_id=owner_history_id).headers["total_matches"] == "1"
            # admins only get their own jobs too
            response = self._tool_runs("cat1", admin=True, history_id=owner_history_id)
            assert response.headers["total_matches"] == "0"
            other_email = f"{uuid4()}@example.org"
            with self._different_user(other_email):
                # another user's public history shows none of their jobs
                response = self._tool_runs("cat1", history_id=owner_history_id)
                assert response.headers["total_matches"] == "0"
                with self.dataset_populator.test_history() as history_id:
                    mapped = self.dataset_populator.run_tool(
                        "cat1", {"input1": {"batch": True, "values": [{"src": "hdca", "id": list_id}]}}, history_id
                    )
                    for job in mapped["jobs"]:
                        self.dataset_populator.wait_for_job(job["id"], assert_ok=True)
                    (row,) = self._tool_runs_table("cat1", history_id=history_id)["rows"]
                    assert row["cells"]["input:input1"]["id"] == list_id
            for action in ("unpublish", "disable_link_access"):
                self._assert_status_code_is_ok(self._put(f"histories/{owner_history_id}/{action}"))
            with self._different_user(other_email):
                (row,) = self._tool_runs_table("cat1", history_id=history_id)["rows"]
                assert row["cells"]["input:input1"] == {"type": "missing", "reason": "inaccessible"}
                assert row["cells"]["output:out_file1"]["type"] == "collection"
            with self._different_user(anon=True):
                assert self._tool_runs("cat1").headers["total_matches"] == "0"

    def _tool_runs(self, tool_id: str, expected_status: int = 200, admin: bool = False, **params) -> Response:
        response = self._get("tool_runs", data={"tool_id": tool_id, **params}, admin=admin)
        self._assert_status_code_is(response, expected_status)
        return response

    def _tool_runs_table(self, tool_id: str, **params) -> dict[str, Any]:
        return self._tool_runs(tool_id, **params).json()

    def _add_workflow_output(self, workflow_id: str, step_label: str, output_name: str, label: str) -> None:
        with self.workflow_populator.export_for_update(workflow_id) as workflow:
            step = next(step for step in workflow["steps"].values() if step["label"] == step_label)
            step["workflow_outputs"].append({"output_name": output_name, "label": label})

    def _output_runs(self, workflow_id: str, expected_status: int = 200, **params) -> Response:
        response = self._get(f"workflows/{workflow_id}/output_runs", data=params)
        self._assert_status_code_is(response, expected_status)
        return response

    def _output_runs_table(self, workflow_id: str, **params) -> dict[str, Any]:
        return self._output_runs(workflow_id, **params).json()

    def _invocation_step(self, invocation_id: str, order_index: int) -> dict[str, Any] | None:
        invocation = self.workflow_populator.get_invocation(invocation_id)
        return next((step for step in invocation["steps"] if step["order_index"] == order_index), None)

    def _list_from(self, history_id: str, element_identifiers: list[dict[str, Any]]) -> str:
        response = self.dataset_collection_populator.create_list_in_history(
            history_id, direct_upload=False, element_identifiers=element_identifiers, wait=True
        )
        self._assert_status_code_is_ok(response)
        return response.json()["id"]

    def _step_runs(self, workflow_id: str, step_label: str, expected_status: int = 200, **params) -> Response:
        response = self._get(f"workflows/{workflow_id}/step_runs", data={"step_label": step_label, **params})
        self._assert_status_code_is(response, expected_status)
        return response

    def _step_runs_table(self, workflow_id: str, step_label: str, **params) -> dict[str, Any]:
        return self._step_runs(workflow_id, step_label, **params).json()

    def _invoke_and_wait(
        self, workflow_id: str, history_id: str, inputs: dict[str, Any], assert_ok: bool = True, **request: Any
    ) -> str:
        response = self.workflow_populator.invoke_workflow_and_wait(
            workflow_id, history_id, inputs, request=request, assert_ok=assert_ok, inputs_by="name"
        )
        return response.json()["id"]

    def _run_two_cat(self, history_id: str, invocations: int = 1) -> RunJobsSummary:
        return self.workflow_populator.run_workflow(WORKFLOW_TWO_CAT, history_id=history_id, invocations=invocations)

    def _rerun(self, summary: RunJobsSummary, **request: Any) -> str:
        workflow_request = {**summary.workflow_request, **request}
        response = self.workflow_populator.invoke_workflow_and_wait(summary.workflow_id, request=workflow_request)
        return response.json()["id"]

    def _refactor(self, workflow_id: str, *actions: dict[str, Any]) -> None:
        response = self.workflow_populator.refactor_workflow(workflow_id, list(actions))
        self._assert_status_code_is_ok(response)

    def _relabel(self, workflow_id: str, old_label: str, new_label: str) -> None:
        action = {"action_type": "update_step_label", "step": {"label": old_label}, "label": new_label}
        self._refactor(workflow_id, action)

    def _run_and_show(self, tool_id: str, inputs: dict, history_id: str) -> dict:
        response = self.dataset_populator.run_tool(tool_id, inputs, history_id)
        job_id = response["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=True)
        return self.dataset_populator.get_job_details(job_id, full=True).json()


def _hda(dataset: dict[str, Any]) -> dict[str, str]:
    return {"src": "hda", "id": dataset["id"]}
