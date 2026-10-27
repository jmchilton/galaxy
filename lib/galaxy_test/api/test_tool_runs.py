from uuid import uuid4

from galaxy_test.base.populators import skip_without_tool
from .test_comparisons import ComparisonsApiTestCase


class TestToolRunsApi(ComparisonsApiTestCase):
    @skip_without_tool("multi_data_param")
    def test_tool_runs_multiple_data_input(self):
        with self.dataset_populator.test_history() as history_id:
            hdas = [self.dataset_populator.new_dataset(history_id, content=f"{i}\n", wait=True) for i in range(3)]
            inputs = {
                "f1": {"batch": False, "values": [self.dataset_populator.ds_entry(hda) for hda in hdas]},
                "f2": self.dataset_populator.ds_entry(hdas[0]),
            }
            self.dataset_populator.run_tool_and_show_job("multi_data_param", inputs, history_id)
            list_id = self._list_from(
                history_id, [{"name": f"el{i}", "src": "hda", "id": hda["id"]} for i, hda in enumerate(hdas[:2])]
            )
            # a reduced collection records its elements as f11, f12... too
            self.dataset_populator.run_tool_and_show_job(
                "multi_data_param",
                {"f1": {"src": "hdca", "id": list_id}, "f2": self.dataset_populator.ds_entry(hdas[0])},
                history_id,
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
                self.dataset_populator.wait_for_jobs(mapped["jobs"], assert_ok=True)
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

                # a batch matches the state filter by the state its row shows
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
                assert rows[0]["run"]["id"] == plain["jobs"][0]["id"]
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
                    self.dataset_populator.wait_for_jobs(mapped["jobs"], assert_ok=True)
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
