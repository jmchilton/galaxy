from unittest.mock import Mock

import pytest

from galaxy.tool_util.output_checker import (
    check_output,
    DETECTED_JOB_STATE,
    oom_kill_job_messages,
    output_discovery_job_message,
)
from galaxy.tool_util.parser.stdio import (
    StdioErrorLevel,
    ToolStdioRegex,
)
from galaxy.util.unittest import TestCase

SLURM_OOM_KILL = (
    "slurmstepd: error: Detected 1 oom-kill event(s) in StepId=5726054.batch. "
    "Some of your processes may have been killed by the cgroup out-of-memory handler."
)


@pytest.mark.parametrize(
    "job_stderr",
    [
        SLURM_OOM_KILL,
        f"some job script noise\n{SLURM_OOM_KILL}\n",
        "slurmstepd: error: Detected 2 oom-kill event(s) in step 7.batch cgroup.",
        "slurmstepd: error: Exceeded job memory limit",
        "galaxy: Detected 3 oom-kill event(s) in the job's memory cgroup.",
    ],
)
def test_oom_kill_job_messages_detects_kills(job_stderr):
    (message,) = oom_kill_job_messages(job_stderr)
    assert message["type"] == "regex"
    assert message["stream"] == "job_stderr"
    assert message["error_level"] == StdioErrorLevel.FATAL_OOM
    assert message["match"] and message["match"] in job_stderr
    assert message["desc"] == f"Out of memory error: {message['match']}"


@pytest.mark.parametrize(
    "job_stderr",
    [
        None,
        "",
        # Slurm can print these without killing anything (galaxy#1426, galaxy#2309).
        "slurmstepd: error: Exceeded job memory limit at some point.",
        "slurmstepd: error: Exceeded step memory limit at some point.",
        # Only the resource manager's own line, not text quoted elsewhere on the line.
        f"tool said: {SLURM_OOM_KILL}",
    ],
)
def test_oom_kill_job_messages_ignores_non_kills(job_stderr):
    assert oom_kill_job_messages(job_stderr) == []


class TestOutputChecker(TestCase):
    def setUp(self):
        self.tool = Mock(
            stdio_regexes=[],
            stdio_exit_codes=[],
        )
        self.stdout = ""
        self.stderr = ""
        self.tool_exit_code = 0

    def test_default_no_stderr_success(self):
        self.__assertSuccessful()

    def test_output_discovery_job_message(self):
        assert output_discovery_job_message()["desc"] == "Failed to collect job outputs"
        assert (
            output_discovery_job_message("Missing collection type")["desc"]
            == "Failed to collect job outputs: Missing collection type"
        )

    def test_default_stderr_failure(self):
        self.stderr = "foo"
        self.__assertNotSuccessful()

    def test_exit_code_error(self):
        mock_exit_code = Mock(range_start=1, range_end=1, error_level=StdioErrorLevel.FATAL, desc=None)
        self.tool.stdio_exit_codes.append(mock_exit_code)
        self.tool_exit_code = 1
        self.__assertNotSuccessful()

    def test_exit_code_success(self):
        mock_exit_code = Mock(range_start=1, range_end=1, error_level=StdioErrorLevel.FATAL, desc=None)
        self.tool.stdio_exit_codes.append(mock_exit_code)
        self.tool_exit_code = 0
        self.__assertSuccessful()

    def test_problematic_strings_matching(self):
        problematic_str = "\x80abc"
        self.__add_regex(
            Mock(match=r".abc", stdout_match=False, stderr_match=True, error_level=StdioErrorLevel.FATAL, desc=None)
        )
        self.stderr = problematic_str
        self.__assertNotSuccessful()

    def test_problematic_strings_not_matching(self):
        problematic_str = "\x80abc"
        self.__add_regex(
            Mock(match=r".abcd", stdout_match=False, stderr_match=True, error_level=StdioErrorLevel.FATAL, desc=None)
        )
        self.stderr = problematic_str
        self.__assertSuccessful()

    def test_stderr_regex_negative_match(self):
        regex = ToolStdioRegex()
        regex.stderr_match = True
        regex.match = "foobar"
        self.__add_regex(regex)
        self.stderr = "foo"
        self.__assertSuccessful()

    def test_stderr_regex_positive_match(self):
        regex = ToolStdioRegex()
        regex.stderr_match = True
        regex.match = "foo"
        self.__add_regex(regex)
        self.stderr = "foobar"
        self.__assertNotSuccessful()

    def test_stderr_regex_group_positive_match(self):
        regex = ToolStdioRegex()
        regex.stderr_match = True
        regex.match = "ERROR: (.{3})bar"
        regex.desc = r"\1"
        self.__add_regex(regex)
        self.stderr = "ERROR: foobar"
        _, _, _, job_messages = self.__check_output()
        assert job_messages[0]["desc"] == "Fatal error: foo"
        self.__assertNotSuccessful()

    def test_stderr_regex_namedgroup_positive_match(self):
        regex = ToolStdioRegex()
        regex.stderr_match = True
        regex.match = "ERROR: (?P<q>.{3})bar"
        regex.desc = r"\g<q>"
        self.__add_regex(regex)
        self.stderr = "ERROR: foobar"
        _, _, _, job_messages = self.__check_output()
        assert job_messages[0]["desc"] == "Fatal error: foo"
        self.__assertNotSuccessful()

    def test_stdout_ignored_for_stderr_regexes(self):
        regex = ToolStdioRegex()
        regex.stderr_match = True
        regex.match = "foo"
        self.__add_regex(regex)
        self.stdout = "foobar"
        self.__assertSuccessful()

    def test_stderr_ignored_for_stdout_regexes(self):
        regex = ToolStdioRegex()
        regex.stdout_match = True
        regex.match = "foo"
        self.__add_regex(regex)
        self.stderr = "foobar"
        self.__assertSuccessful()

    def __add_regex(self, regex):
        self.tool.stdio_regexes.append(regex)

    def __assertSuccessful(self):
        assert self.__check_output()[0] == DETECTED_JOB_STATE.OK

    def __assertNotSuccessful(self):
        assert self.__check_output()[0] != DETECTED_JOB_STATE.OK

    def __check_output(self):
        return check_output(
            self.tool.stdio_regexes, self.tool.stdio_exit_codes, self.stdout, self.stderr, self.tool_exit_code
        )
