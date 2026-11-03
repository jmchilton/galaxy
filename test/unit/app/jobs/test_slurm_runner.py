import pytest

from galaxy.jobs.runners.slurm import (
    check_memory_limit,
    OUT_OF_MEMORY_MSG,
    PROBABLY_OUT_OF_MEMORY_MSG,
)


@pytest.mark.parametrize(
    "stderr, expected",
    [
        ("slurmstepd: error: Exceeded job memory limit\n", OUT_OF_MEMORY_MSG),
        (
            "slurmstepd: error: Detected 1 oom-kill event(s) in StepId=5726054.batch. "
            "Some of your processes may have been killed by the cgroup out-of-memory handler.\n",
            OUT_OF_MEMORY_MSG,
        ),
        ("slurmstepd: error: Exceeded job memory limit at some point.\n", PROBABLY_OUT_OF_MEMORY_MSG),
        ("slurmstepd: error: Exceeded step memory limit at some point.\n", PROBABLY_OUT_OF_MEMORY_MSG),
        (
            "slurmstepd: error: Exceeded job memory limit at some point.\n"
            "slurmstepd: error: Detected 1 oom-kill event(s) in StepId=1.batch.\n",
            OUT_OF_MEMORY_MSG,
        ),
        ("slurmstepd: error: *** JOB 1 ON node CANCELLED AT 2026-10-28T16:37:20 ***\n", None),
    ],
)
def test_check_memory_limit(tmp_path, stderr, expected):
    error_file = tmp_path / "galaxy_1.e"
    error_file.write_text(stderr)
    assert check_memory_limit(str(error_file)) == expected


def test_check_memory_limit_reads_only_the_tail(tmp_path):
    error_file = tmp_path / "galaxy_1.e"
    error_file.write_text("slurmstepd: error: Exceeded job memory limit\n" + "x" * 4096 + "\n")
    assert check_memory_limit(str(error_file)) is None
    error_file.write_text("x" * 4096 + "\nslurmstepd: error: Exceeded job memory limit\n")
    assert check_memory_limit(str(error_file)) == OUT_OF_MEMORY_MSG


def test_check_memory_limit_missing_file(tmp_path):
    assert check_memory_limit(str(tmp_path / "galaxy_1.e")) is None
