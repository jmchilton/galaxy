"""Tool patch collections applied at tool load, end to end."""

import os
import tempfile

from galaxy.tool_util.parser import get_tool_source
from galaxy.util import galaxy_directory
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

FIXTURES = os.path.join(galaxy_directory(), "test", "functional", "tool_patches")
FUNCTIONAL_TOOLS = os.path.join(galaxy_directory(), "test", "functional", "tools")
TOOL_ID = "identifier_single"


class BaseToolPatchesIntegrationTestCase(integration_util.IntegrationTestCase):
    framework_tool_and_types = True
    collection: str = "identifier_single"

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

    def _run_identifier_single(self, history_id: str, hda_id: str, use_cached_job: bool = False) -> dict:
        run = self.dataset_populator.run_tool(
            TOOL_ID, {"input1": {"src": "hda", "id": hda_id}}, history_id, use_cached_job=use_cached_job
        )
        self.dataset_populator.wait_for_job(run["jobs"][0]["id"], assert_ok=True)
        return run

    def _output_file_name(self, run: dict) -> str:
        return self._get(f"datasets/{run['outputs'][0]['id']}").json()["file_name"]

    def _assert_job_cache_reuse(self, reused: bool) -> None:
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", wait=True)
            first = self._run_identifier_single(history_id, hda["id"])
            second = self._run_identifier_single(history_id, hda["id"], use_cached_job=True)
            assert (self._output_file_name(first) == self._output_file_name(second)) is reused


class TestToolPatchApplied(BaseToolPatchesIntegrationTestCase):
    def test_api_reports_patch(self):
        (state,) = self._patch_states()
        assert state["state"] == "applied"
        assert state["key"] == "_local/identifier_single/1.0.0"
        assert state["reproducibility"] == "special_inputs"
        assert "contained a dot" in state["reproducibility_doc"]

    def test_job_runs_patched_command(self):
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", name="a.b", wait=True)
            run = self._run_identifier_single(history_id, hda["id"])
            content = self.dataset_populator.get_history_dataset_content(history_id, dataset=run["outputs"][0])
            assert content.splitlines()[0] == "identifier a_b"

    def test_special_inputs_patch_skips_job_cache(self):
        self._assert_job_cache_reuse(False)


class TestToolPatchRejectsInputsKeepsJobCache(BaseToolPatchesIntegrationTestCase):
    collection = "identifier_single_validator"

    def test_rejects_inputs_patch_reuses_job_cache(self):
        (state,) = self._patch_states()
        assert (state["state"], state["reproducibility"]) == ("applied", "rejects_inputs")
        self._assert_job_cache_reuse(True)


class TestToolPatchAlreadyApplied(BaseToolPatchesIntegrationTestCase):
    """The same id and version, already holding the patched text."""

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        conf_dir = tempfile.mkdtemp()
        conf_path = os.path.join(conf_dir, "tool_patches_fixed_conf.xml")
        with open(conf_path, "w") as f:
            f.write(f'<toolbox tool_path="{FUNCTIONAL_TOOLS}"><tool file="identifier_single_fixed.xml" /></toolbox>')
        config["tool_config_file"] = conf_path

    def test_already_applied_leaves_source_unchanged(self):
        (state,) = self._patch_states()
        assert state["state"] == "already_applied"
        tool = self._app.toolbox.get_tool(TOOL_ID)
        unpatched = get_tool_source(os.path.join(FUNCTIONAL_TOOLS, "identifier_single_fixed.xml"))
        assert tool.tool_source.to_string() == unpatched.to_string()
