"""The jobs of the tool security review spec, through the evaluators that prepare real jobs."""

import re

import pytest

from galaxy.app_unittest_utils.security_review_spec import (
    EVALUATORS,
    SpecJobRunner,
)
from galaxy.tool_util.security.spec import (
    expected_codes,
    iter_jobs,
    load_cases,
)
from galaxy.tools.security_review import LOG

CASES = load_cases()
JOBS = list(iter_jobs(CASES))
# The codes a warning of the review starts with.
WARNING_CODES = re.compile(r"^Tool security review \(([^)]*)\)")


def _params(jobs):
    return [pytest.param(*job, id=f"{job[0]}-{job[1]}-{job[2]}") for job in jobs]


@pytest.fixture
def runner(tmp_path):
    return lambda case_id: SpecJobRunner(CASES[case_id].tool, str(tmp_path))


@pytest.mark.parametrize("evaluator", sorted(EVALUATORS))
@pytest.mark.parametrize("case_id,color,index,job", _params(JOBS))
def test_job(runner, case_id, color, index, job, evaluator):
    outcome = runner(case_id).run(job, evaluator=evaluator)
    assert outcome.rejected is job.expect.rejected, outcome.message
    assert outcome.codes == expected_codes(CASES[case_id], job)
    for fragment in job.expect.message_contains:
        assert outcome.message and fragment in outcome.message
    if outcome.rejected:
        assert outcome.warnings


@pytest.mark.parametrize("case_id,color,index,job", _params(j for j in JOBS if j[3].expect.rejected))
def test_log_mode_runs_and_warns(runner, case_id, color, index, job):
    outcome = runner(case_id).run(job, mode=LOG)
    assert not outcome.rejected
    warned = {code for w in outcome.warnings if (m := WARNING_CODES.match(w)) for code in m.group(1).split(", ")}
    assert warned == {code.value for code in expected_codes(CASES[case_id], job)}


@pytest.mark.parametrize("case_id,color,index,job", _params(j for j in JOBS if j[3].harm))
def test_harm(runner, case_id, color, index, job):
    harmed, returncode = runner(case_id).harms(job)
    assert harmed is (color == "red")
    if color == "green":
        # A command that does not run shows no harm either.
        assert returncode == 0
