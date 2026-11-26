"""Tool patch collections applied at tool load, end to end."""

import os
from typing import Any

from galaxy.tool_util.parser import get_tool_source
from galaxy.util import galaxy_directory
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

FIXTURES = os.path.join(galaxy_directory(), "test", "functional", "tool_patches")
FUNCTIONAL_TOOLS = os.path.join(galaxy_directory(), "test", "functional", "tools")
TOOL_ID = "identifier_single"


def _inputs(hda_id: str) -> dict[str, Any]:
    return {"input1": {"src": "hda", "id": hda_id}}


class BaseToolPatchesIntegrationTestCase(integration_util.IntegrationTestCase):
    framework_tool_and_types = True
    collection: str = "identifier_single"
    dataset_populator: DatasetPopulator

    def setUp(self) -> None:
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        config["tool_patch_paths"] = [os.path.join(FIXTURES, cls.collection)]

    def _patch_states(self) -> list[dict]:
        response = self._get(f"tools/{TOOL_ID}")
        self._assert_status_code_is(response, 200)
        return response.json()["patches"]

    def _raw_tool_source(self) -> str:
        response = self._get(f"tools/{TOOL_ID}/raw_tool_source", admin=True)
        self._assert_status_code_is(response, 200)
        return response.text

    def _run_identifier_single(self, history_id: str, hda_id: str, use_cached_job: bool = False) -> dict:
        run = self.dataset_populator.run_tool(TOOL_ID, _inputs(hda_id), history_id, use_cached_job=use_cached_job)
        self.dataset_populator.wait_for_job(run["jobs"][0]["id"], assert_ok=True)
        return run

    def _run_job(self, history_id: str, hda_id: str, use_cached_job: bool = False) -> str:
        return self._run_identifier_single(history_id, hda_id, use_cached_job=use_cached_job)["jobs"][0]["id"]

    def _run_tool_request_job(self, history_id: str, hda_id: str) -> str:
        """Run through the tool request API with the job cache on; returns the job id."""
        response = self.dataset_populator.tool_request_raw(TOOL_ID, _inputs(hda_id), history_id, use_cached_jobs=True)
        self._assert_status_code_is(response, 200)
        tool_request_id = response.json()["tool_request_id"]
        assert self.dataset_populator.wait_on_tool_request(tool_request_id)
        (job,) = self.galaxy_interactor.jobs_for_tool_request(tool_request_id)
        self.dataset_populator.wait_for_job(job["id"], assert_ok=True)
        return job["id"]

    def _copied_from_job_id(self, job_id: str) -> str | None:
        return self.dataset_populator.get_job_details(job_id, full=True).json()["copied_from_job_id"]

    def _assert_job_cache_reuse(self, reused: bool, via_tool_request: bool = False) -> None:
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", wait=True)
            first = self._run_job(history_id, hda["id"])
            if via_tool_request:
                second = self._run_tool_request_job(history_id, hda["id"])
            else:
                second = self._run_job(history_id, hda["id"], use_cached_job=True)
            assert self._copied_from_job_id(second) == (first if reused else None)

    def _assert_job_search_finds_job(self, found: bool) -> None:
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", wait=True)
            first = self._run_job(history_id, hda["id"])
            self.dataset_populator.wait_for_history(history_id, assert_ok=True)
            jobs = self.dataset_populator.search_jobs(TOOL_ID, _inputs(hda["id"]), history_id)
            assert [job["id"] for job in jobs] == ([first] if found else [])


class TestToolPatchApplied(BaseToolPatchesIntegrationTestCase):
    def test_api_reports_patch(self):
        (state,) = self._patch_states()
        assert state["state"] == "applied"
        assert state["key"] == "_local/identifier_single/1.0.0"
        assert state["reproducibility"] == "unusual_inputs"
        assert "contained a dot" in state["reproducibility_doc"]
        assert "#set $clean_identifier" in self._raw_tool_source()

    def test_job_runs_patched_command(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", name="a.b", wait=True)
            run = self._run_identifier_single(history_id, hda["id"])
            content = self.dataset_populator.get_history_dataset_content(history_id, dataset=run["outputs"][0])
            assert content.splitlines()[0] == "identifier a_b"

    def test_unusual_inputs_patch_skips_job_cache(self):
        self._assert_job_cache_reuse(False)

    def test_unusual_inputs_patch_skips_job_cache_for_tool_requests(self):
        self._assert_job_cache_reuse(False, via_tool_request=True)

    def test_unusual_inputs_patch_hides_jobs_from_search(self):
        self._assert_job_search_finds_job(False)


class TestToolPatchAppliedCachedToolbox(TestToolPatchApplied):
    """The populator stores the patched source and the index carries its state."""

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        config["use_cached_toolbox"] = True


class TestToolPatchRejectsInputsKeepsJobCache(BaseToolPatchesIntegrationTestCase):
    collection = "identifier_single_validator"

    def test_rejects_inputs_patch_reuses_job_cache(self):
        (state,) = self._patch_states()
        assert (state["state"], state["reproducibility"]) == ("applied", "rejects_inputs")
        self._assert_job_cache_reuse(True)
        self._assert_job_cache_reuse(True, via_tool_request=True)
        self._assert_job_search_finds_job(True)


class TestToolPatchAlreadyApplied(BaseToolPatchesIntegrationTestCase):
    """The same id and version, already holding the patched text."""

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        conf_dir = cls.temp_config_dir("tool_patches_fixed")
        os.makedirs(conf_dir, exist_ok=True)
        conf_path = os.path.join(conf_dir, "tool_patches_fixed_conf.xml")
        with open(conf_path, "w") as f:
            f.write(f'<toolbox tool_path="{FUNCTIONAL_TOOLS}"><tool file="identifier_single_fixed.xml" /></toolbox>')
        config["tool_config_file"] = conf_path

    def test_already_applied_leaves_source_unchanged(self):
        (state,) = self._patch_states()
        assert state["state"] == "already_applied"
        unpatched = get_tool_source(os.path.join(FUNCTIONAL_TOOLS, "identifier_single_fixed.xml"))
        assert self._raw_tool_source() == unpatched.to_string()
