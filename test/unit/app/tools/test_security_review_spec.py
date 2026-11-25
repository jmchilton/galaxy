"""The jobs of the tool security review spec, through the evaluators that prepare real jobs."""

import re

import pytest

from galaxy.app_unittest_utils.security_review_spec import (
    EVALUATORS,
    JobOutcome,
    SpecJobRunner,
)
from galaxy.tool_util.security.spec import (
    expected_codes,
    expected_warnings,
    iter_jobs,
    load_cases,
    sweep_jobs,
)
from galaxy.tools.parameters.basic import ParameterValueError
from galaxy.tools.security_review import (
    ENFORCE_ALL,
    LOG,
)

CASES = load_cases()
JOBS = list(iter_jobs(CASES))
# The codes a warning of the review starts with.
WARNING_CODES = re.compile(r"^Tool security review \(([^)]*)\)")


def _params(jobs):
    return [pytest.param(*job, id=f"{job.case_id}-{job.color}-{job.position}") for job in jobs]


def _warned_codes(outcome: JobOutcome) -> set[str]:
    return {code for w in outcome.warnings if (m := WARNING_CODES.match(w)) for code in m.group(1).split(", ")}


@pytest.fixture
def runner(tmp_path):
    return lambda case_id: SpecJobRunner(CASES[case_id].tool, str(tmp_path))


@pytest.mark.parametrize("evaluator", sorted(EVALUATORS))
@pytest.mark.parametrize("case_id,color,index,job", _params(JOBS))
def test_job(runner, case_id, color, index, job, evaluator):
    outcome = runner(case_id).run(job, evaluator=evaluator)
    codes = expected_codes(CASES[case_id], job)
    assert outcome.rejected is job.expect.rejected, outcome.message
    assert outcome.codes == codes
    assert _warned_codes(outcome) == {code.value for code in expected_warnings(CASES[case_id], job)}
    if outcome.rejected:
        # Galaxy keeps the first 255 characters of a job's info.
        assert outcome.message and outcome.message.startswith(
            f"[{', '.join(code.value for code in codes)}] This job was not run: "
        )
    for fragment in job.expect.message_contains:
        assert outcome.message and fragment in outcome.message


@pytest.mark.parametrize("case_id,color,index,job", _params(JOBS))
def test_log_mode_runs_and_warns_with_the_codes(runner, case_id, color, index, job):
    spec_runner = runner(case_id)
    outcome = spec_runner.run(job, mode=LOG)
    assert not outcome.rejected
    # Log mode warns of all that enforce_all refuses, which stops at the first refusal.
    strictest = spec_runner.run(job, mode=ENFORCE_ALL)
    warned = _warned_codes(outcome)
    assert {code.value for code in strictest.codes} | _warned_codes(strictest) <= warned
    assert {code.value for code in expected_warnings(CASES[case_id], job)} <= warned


@pytest.mark.parametrize("case_id,color,index,job", _params(j for j in JOBS if j.job.harm))
def test_harm(runner, case_id, color, index, job):
    harmed, returncode = runner(case_id).harms(job)
    assert harmed is (color == "red")
    if color == "green":
        # A command that does not run shows no harm either.
        assert returncode == 0


@pytest.mark.parametrize(
    "case_id,slot,job",
    [
        pytest.param(s.case_id, s.slot, s.job, id=f"{s.case_id}-green-{s.base}-{s.slot}-{s.payload_index}")
        for s in sweep_jobs(CASES)
    ],
)
def test_sweep_refuses_or_stays_harmless(runner, case_id, slot, job):
    spec_runner = runner(case_id)
    try:
        outcome = spec_runner.run(job)
    except ParameterValueError:
        # The tool's own validator refuses the value.
        assert slot.startswith("inputs.")
        return
    if not outcome.rejected:
        harmed, _ = spec_runner.harms(job)
        assert not harmed, outcome.command_line
