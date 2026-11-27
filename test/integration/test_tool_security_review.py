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
UNSURE_TOOL_ID = "security_review_unsure_identifiers"
# The review does not follow what a template reads from the template object, so it cannot judge
# what this tool writes: by default the job's values must be plain.
UNSURE_TOOL = TOOL.replace(TOOL_ID, UNSURE_TOOL_ID).replace("#end for", "#end for\necho '$searchList' >> '$out_file1';")
PIPING_TOOL_ID = "security_review_pipe_identifiers"
# A value sent to a shell to run is code whatever its characters: by default every job is refused.
PIPING_TOOL = TOOL.replace(TOOL_ID, PIPING_TOOL_ID).replace(
    "echo '$e.element_identifier' >> '$out_file1';", "echo 'echo $e.element_identifier' | sh >> '$out_file1';"
)
# Leaves the single quotes and pipes into another command: `echo 'a'|'cat' >> out` writes a.
QUOTED = "a'|'cat"


class _CapturedWarnings(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class BaseToolSecurityReviewTestCase(integration_util.IntegrationTestCase):
    dataset_populator: DatasetPopulator
    dataset_collection_populator: DatasetCollectionPopulator
    # None leaves the server's default.
    mode: str | None

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        tool_dir = tempfile.mkdtemp()
        with open(os.path.join(tool_dir, "echo_identifiers.xml"), "w") as fh:
            fh.write(TOOL)
        with open(os.path.join(tool_dir, "pipe_identifiers.xml"), "w") as fh:
            fh.write(PIPING_TOOL)
        with open(os.path.join(tool_dir, "unsure_identifiers.xml"), "w") as fh:
            fh.write(UNSURE_TOOL)
        tool_conf = os.path.join(tool_dir, "tool_conf.xml")
        with open(tool_conf, "w") as fh:
            fh.write(
                f'<toolbox tool_path="{tool_dir}"><tool file="echo_identifiers.xml"/>'
                '<tool file="pipe_identifiers.xml"/><tool file="unsure_identifiers.xml"/></toolbox>'
            )
        config["tool_config_file"] = f"{config['tool_config_file']},{tool_conf}"
        if cls.mode is not None:
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

    def _run(self, history_id: str, identifier: str, tool_id: str = TOOL_ID) -> dict:
        hdca = self.dataset_collection_populator.create_list_in_history(
            history_id, contents=[(identifier, "x\n")], wait=True
        ).json()["output_collections"][0]
        run = self.dataset_populator.run_tool(tool_id, {"input": {"src": "hdca", "id": hdca["id"]}}, history_id)
        job_id = run["jobs"][0]["id"]
        self.dataset_populator.wait_for_job(job_id, assert_ok=False)
        output = self.dataset_populator.get_history_dataset_details(
            history_id, dataset_id=run["outputs"][0]["id"], assert_ok=False
        )
        return {"job": self.dataset_populator.get_job_details(job_id).json(), "output": output}

    def _review_warnings(self) -> list[str]:
        return [m for m in self.warnings.messages if TOOL_ID in m and "input 'input'" in m]

    def _assert_runs(self, history_id: str, identifier: str, tool_id: str = TOOL_ID) -> dict:
        result = self._run(history_id, identifier, tool_id)
        assert result["job"]["state"] == "ok", result
        return result


class TestToolSecurityReviewEnforce(BaseToolSecurityReviewTestCase):
    mode = "enforce_code"

    def test_identifier_that_leaves_its_quotes_fails_the_job(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._run(history_id, QUOTED)
            assert result["job"]["state"] == "error"
            message = result["output"]["misc_info"]
            assert message.startswith("[shell-injection] This job was not run: ")
            assert "an element identifier or the name of input 'input' contains the characters [' |]" in message
            assert "known problem handling these characters" in message
            assert len(self._review_warnings()) == 1

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
            # The identifier left the quotes of the template and ran `cat`.
            assert content.strip() == "a"
            (warning,) = self._review_warnings()
            assert "contains [' |]" in warning and "shell-injection" in warning
            assert QUOTED not in warning

    def test_harmless_identifier_runs(self):
        with self.dataset_populator.test_history() as history_id:
            self._assert_runs(history_id, "sample_1")
            assert self._review_warnings() == []


class TestToolSecurityReviewDefaults(BaseToolSecurityReviewTestCase):
    mode = None

    def test_value_the_review_cannot_judge_must_be_plain(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._assert_runs(history_id, "sample_1", UNSURE_TOOL_ID)
            content = self.dataset_populator.get_history_dataset_content(history_id, dataset_id=result["output"]["id"])
            assert content.startswith("sample_1")
            result = self._run(history_id, "50%", UNSURE_TOOL_ID)
            assert result["job"]["state"] == "error"
            message = result["output"]["misc_info"]
            # Galaxy keeps the first 255 characters of the message.
            assert message.startswith(
                "[not-plain-unchecked-place] This job was not run: an element identifier or the name of input 'input'"
                " contains [%]"
            )
            assert "Use letters, digits" in message

    def test_value_sent_to_a_shell_to_run_is_refused_whatever_it_is(self):
        with self.dataset_populator.test_history() as history_id:
            result = self._run(history_id, "sample_1", PIPING_TOOL_ID)
            assert result["job"]["state"] == "error"
            assert result["output"]["misc_info"].startswith(
                "[uncheckable-letters-are-code] This job was not run: this Galaxy server cannot check any value for tool"
            )

    def test_galaxy_upload_tool_runs(self):
        # upload1 reads the outputs Galaxy gives its jobs by computed name, but it is Galaxy's own.
        with self.dataset_populator.test_history() as history_id:
            hda = self.dataset_populator.new_dataset(history_id, content="1\n", fetch_data=False)
            self.dataset_populator.wait_for_history(history_id, assert_ok=False)
            output = self.dataset_populator.get_history_dataset_details(history_id, dataset=hda, assert_ok=False)
        assert output["state"] == "ok", output


class TestToolSecurityReviewDefaultsCachedToolbox(TestToolSecurityReviewDefaults):
    """The cached toolbox builds tools from its tool source store, without their tool file."""

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["use_cached_toolbox"] = True


class TestToolSecurityReviewNotStrict(BaseToolSecurityReviewTestCase):
    mode = "enforce_code"

    @classmethod
    def handle_galaxy_config_kwds(cls, config):
        super().handle_galaxy_config_kwds(config)
        config["tool_security_review_when_unsure"] = "log"

    def test_value_the_review_cannot_judge_runs(self):
        with self.dataset_populator.test_history() as history_id:
            self._assert_runs(history_id, "50%", UNSURE_TOOL_ID)
            self._assert_runs(history_id, "sample_1", PIPING_TOOL_ID)
