"""Jobs of tools whose static review keeps findings after their tool patches are refused."""

from pathlib import Path

from galaxy.tool_util.unittest_utils import functional_test_tool_path
from galaxy.tool_util.unittest_utils.tool_patches import (
    replace_text_op,
    security_patch,
    write_collection,
)
from galaxy_test.base.populators import DatasetPopulator
from galaxy_test.driver import integration_util

IDENTIFIER_TOOL = Path(functional_test_tool_path("identifier_single.xml")).read_text()
ECHO = "echo 'identifier $input1.element_identifier' > 'output1';"
DOC = "Jobs whose input identifier held other characters than letters, digits, '_', '-' and '.' now print them as '_'."
CLEANING = security_patch(
    [
        replace_text_op(
            "command",
            ECHO,
            "#import re\n"
            '#set $clean_identifier = $re.sub(r"[^\\w.-]", "_", str($input1.element_identifier))\n'
            "echo 'identifier $clean_identifier' > 'output1';",
        )
    ],
    "unusual_inputs",
    DOC,
)
# A sanitizer that lets `;` through: nested-interpreter is high, and medium once the patch takes `;` out.
AWK_TOOL = """<tool id="static_lowered" name="static_lowered" version="1.0">
    <command><![CDATA[awk 'BEGIN { print $x }' > '$out']]></command>
    <inputs>
        <param name="x" type="text" value="a">
            <sanitizer invalid_char=""><valid initial="string.letters"><add value=";"/></valid></sanitizer>
        </param>
    </inputs>
    <outputs><data name="out" format="txt"/></outputs>
</tool>
"""
LOWERING = security_patch(
    [
        {
            "replace_element": {
                "path": "inputs/param[@name='x']/sanitizer/valid/add",
                "old": '<add value=";"/>',
                "new": '<add value="/"/>',
                "occurrences": 1,
            }
        }
    ],
    "ordinary_inputs",
    "Jobs whose value of x held ';' now run without it.",
)
REFUSED = "[static-findings] This job was not run: the security review of this tool reports"


class TestStaticFindingsRefusal(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        tool_dir = Path(cls.temp_config_dir("static_findings_refusal"))
        tool_dir.mkdir(parents=True, exist_ok=True)
        for tool_id in ("static_refused", "static_cleaned"):
            (tool_dir / f"{tool_id}.xml").write_text(
                IDENTIFIER_TOOL.replace('id="identifier_single"', f'id="{tool_id}"')
            )
        (tool_dir / "static_lowered.xml").write_text(AWK_TOOL)
        tools = "".join(f'<tool file="{name}.xml"/>' for name in ("static_refused", "static_cleaned", "static_lowered"))
        conf = tool_dir / "tool_conf.xml"
        conf.write_text(f'<toolbox tool_path="{tool_dir}">{tools}</toolbox>')
        collection = write_collection(
            tool_dir / "patches",
            {"_local/static_cleaned/1.0.0.yml": CLEANING, "_local/static_lowered/1.0.yml": LOWERING},
        )
        config["tool_config_file"] = f"{config['tool_config_file']},{conf}"
        config["tool_patch_paths"] = [str(collection)]
        config["tool_security_refuse_static_findings"] = True
        config["tool_security_refuse_static_findings_severity"] = "medium"

    def setUp(self) -> None:
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)

    def _run(self, tool_id: str, inputs: dict, history_id: str) -> tuple[str, dict]:
        run = self.dataset_populator.run_tool(tool_id, inputs, history_id)
        job_id = run["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=False)
        state = self.dataset_populator.get_job_details(job_id).json()["state"]
        output = self.dataset_populator.get_history_dataset_details(
            history_id, dataset_id=run["outputs"][0]["id"], assert_ok=False
        )
        return state, output

    def _run_identifier_tool(self, tool_id: str) -> tuple[str, dict]:
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", name="a;b", wait=True)
            return self._run(tool_id, {"input1": {"src": "hda", "id": hda["id"]}}, history_id)

    def test_tool_with_findings_loads_but_its_jobs_are_refused(self):
        self._assert_status_code_is(self._get("tools/static_refused"), 200)
        state, output = self._run_identifier_tool("static_refused")
        assert state == "error"
        assert output["misc_info"].startswith(f"{REFUSED} shell-injection, and this Galaxy server does not run")
        assert "(static_refused version 1.0.0)" in output["misc_info"]

    def test_tool_patched_clean_runs(self):
        state, output = self._run_identifier_tool("static_cleaned")
        assert state == "ok", output

    def test_finding_a_patch_only_lowered_still_refuses(self):
        (patch,) = self._get("tools/static_lowered").json()["patches"]
        assert patch["state"] == "applied"
        with self.dataset_populator.test_history() as history_id:
            state, output = self._run("static_lowered", {"x": "a"}, history_id)
        assert state == "error"
        assert output["misc_info"].startswith(f"{REFUSED} nested-interpreter, and")


class TestStaticFindingsRefusalCachedToolbox(TestStaticFindingsRefusal):
    """The populator keeps the review on the index entry the materialized tool reads."""

    @classmethod
    def handle_galaxy_config_kwds(cls, config) -> None:
        super().handle_galaxy_config_kwds(config)
        config["use_cached_toolbox"] = True
