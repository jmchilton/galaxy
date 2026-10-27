from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
    skip_without_tool,
    WorkflowPopulator,
)
from ._framework import ApiTestCase


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

    def _run_and_show(self, tool_id: str, inputs: dict, history_id: str) -> dict:
        response = self.dataset_populator.run_tool(tool_id, inputs, history_id)
        job_id = response["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=True)
        return self.dataset_populator.get_job_details(job_id, full=True).json()
