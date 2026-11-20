"""Job values are checked against the security review of the tool before the command line is built."""

import logging
import os
import tempfile

from galaxy.tools import security_review
from galaxy_test.base.populators import (
    DatasetCollectionPopulator,
    DatasetPopulator,
)
from galaxy_test.driver import integration_util

TOOL_ID = "security_review_echo_identifiers"
TOOL = f"""<tool id="{TOOL_ID}" name="Echo identifiers" version="1.0" profile="24.0">
  <command><![CDATA[
#for $e in $input
echo '$e.element_identifier' >> '$out_file1';
#end for
  ]]></command>
  <inputs>
    <param name="input" type="data_collection" collection_type="list" format="txt"/>
  </inputs>
  <outputs>
    <data name="out_file1" format="txt"/>
  </outputs>
</tool>
"""
# Closes the single quotes in the command, and keeps it valid shell: `echo 'a'b'c'` writes abc.
QUOTED = "a'b'c"


class _CapturedWarnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class BaseToolSecurityReviewTestCase(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator
    dataset_collection_populator: DatasetCollectionPopulator
    mode: str

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        tool_dir = tempfile.mkdtemp()
        with open(os.path.join(tool_dir, "echo_identifiers.xml"), "w") as fh:
            fh.write(TOOL)
        tool_conf = os.path.join(tool_dir, "tool_conf.xml")
        with open(tool_conf, "w") as fh:
            fh.write(f'<toolbox tool_path="{tool_dir}"><tool file="echo_identifiers.xml"/></toolbox>')
        config["tool_config_file"] = f"{config['tool_config_file']},{tool_conf}"
        config["tool_security_review"] = cls.mode

    def setUp(self):
        super().setUp()
        self.dataset_populator = DatasetPopulator(self.galaxy_interactor)
        self.dataset_collection_populator = DatasetCollectionPopulator(self.galaxy_interactor)
        self.warnings = _CapturedWarnings()
        logging.getLogger(security_review.__name__).addHandler(self.warnings)

    def tearDown(self):
        logging.getLogger(security_review.__name__).removeHandler(self.warnings)
        super().tearDown()

    def _run(self, history_id: str, identifier: str) -> dict:
        hdca = self.dataset_collection_populator.create_list_in_history(
            history_id, contents=[(identifier, "x\n")], wait=True
        ).json()["output_collections"][0]
        run = self.dataset_populator.run_tool(TOOL_ID, {"input": {"src": "hdca", "id": hdca["id"]}}, history_id)
        job_id = run["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=False)
        output = self.dataset_populator.get_history_dataset_details(
            history_id, dataset_id=run["outputs"][0]["id"], assert_ok=False
        )
        return {"job": self.dataset_populator.get_job_details(job_id).json(), "output": output}

    def _review_warnings(self) -> list[str]:
        return [m for m in self.warnings.messages if TOOL_ID in m and "input 'input'" in m]

    def _assert_runs(self, history_id: str, identifier: str) -> dict:
        result = self._run(history_id, identifier)
        assert result["job"]["state"] == "ok", result
        return result


class TestToolSecurityReviewEnforce(BaseToolSecurityReviewTestCase):
    mode = "enforce"

    def test_identifier_that_leaves_its_quotes_fails_the_job(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._run(history_id, QUOTED)
            assert result["job"]["state"] == "error"
            message = result["output"]["misc_info"]
            assert "This job was not run" in message
            assert "an element identifier or the name of input 'input' contains the characters [']" in message
            assert "known problem handling these characters" in message
            assert len(self._review_warnings()) == 1
            # The review was stored for the other Galaxy processes.
            cache_dir = self._app.config.tool_security_review_cache_dir
            assert any(f.endswith(".json") for _, _, files in os.walk(cache_dir) for f in files)

    def test_harmless_identifier_runs(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._assert_runs(history_id, "sample_1")
            content = self.dataset_populator.get_history_dataset_content(history_id, dataset_id=result["output"]["id"])
            assert content.strip() == "sample_1"
            assert self._review_warnings() == []


class TestToolSecurityReviewLog(BaseToolSecurityReviewTestCase):
    mode = "log"

    def test_identifier_that_leaves_its_quotes_is_logged(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._assert_runs(history_id, QUOTED)
            content = self.dataset_populator.get_history_dataset_content(history_id, dataset_id=result["output"]["id"])
            # The quotes in the identifier closed and reopened the ones in the template.
            assert content.strip() == "abc"
            (warning,) = self._review_warnings()
            assert "contains [']" in warning and "shell-injection" in warning
            assert QUOTED not in warning

    def test_harmless_identifier_runs(self):
        with self.dataset_populator.test_history() as history_id:
            self._assert_runs(history_id, "sample_1")
            assert self._review_warnings() == []
