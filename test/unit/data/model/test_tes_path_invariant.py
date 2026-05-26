"""Red-green tests for the "ICJ supersedes constituent Job" invariant
enforced by ``__strict_check_before_flush__`` on ``Job`` and
``ImplicitCollectionJobs``.

The invariant: when an ICJ carries a ``tool_execution_state_id``, its
constituent Jobs must NOT carry their own direct TES FK — the ICJ is
the canonical anchor for the mapped execution event. WIS and TR are
explicitly allowed to co-point at the same TES row (request side +
materialized side); only Job-vs-ICJ is the forbidden duplication.

These tests call the strict-check methods directly to keep the
assertions deterministic without an SA session, mirroring how the
existing HDA history_id strict check is tested.
"""

import pytest

from galaxy import model


def _job_with_icj_assoc(tool_execution_state_id=None):
    job = model.Job()
    job.tool_execution_state_id = tool_execution_state_id
    job.implicit_collection_jobs_association = model.ImplicitCollectionJobsJobAssociation()
    return job


def test_job_under_icj_with_tes_fk_raises():
    job = _job_with_icj_assoc(tool_execution_state_id=7)

    with pytest.raises(Exception, match="under an ImplicitCollectionJobs also carries"):
        job.__strict_check_before_flush__()


def test_job_under_icj_without_tes_fk_passes():
    job = _job_with_icj_assoc(tool_execution_state_id=None)

    job.__strict_check_before_flush__()


def test_standalone_job_with_tes_fk_passes():
    job = model.Job()
    job.tool_execution_state_id = 7

    job.__strict_check_before_flush__()


def test_wis_has_no_strict_check():
    """WIS may freely co-point at the same TES as its Job (simple) or
    ICJ (mapped). The class deliberately defines no
    ``__strict_check_before_flush__`` — the model's flush guard skips
    objects without one."""
    wis = model.WorkflowInvocationStep()
    assert not hasattr(wis, "__strict_check_before_flush__")


def test_icj_with_tes_and_constituent_job_with_tes_raises():
    icj = model.ImplicitCollectionJobs()
    icj.id = 12
    icj.tool_execution_state_id = 9
    job = model.Job()
    job.id = 4
    job.tool_execution_state_id = 9
    assoc = model.ImplicitCollectionJobsJobAssociation()
    assoc.job = job
    icj.jobs = [assoc]

    with pytest.raises(Exception, match="constituent Job"):
        icj.__strict_check_before_flush__()


def test_icj_with_tes_and_constituent_jobs_null_passes():
    icj = model.ImplicitCollectionJobs()
    icj.id = 12
    icj.tool_execution_state_id = 9
    job1 = model.Job()
    job1.tool_execution_state_id = None
    job2 = model.Job()
    job2.tool_execution_state_id = None
    assoc1 = model.ImplicitCollectionJobsJobAssociation()
    assoc1.job = job1
    assoc2 = model.ImplicitCollectionJobsJobAssociation()
    assoc2.job = job2
    icj.jobs = [assoc1, assoc2]

    icj.__strict_check_before_flush__()


def test_icj_without_tes_does_not_check_constituents():
    """ICJ-side check is a no-op when ICJ doesn't carry the TES link
    itself (e.g. pre-mapped or non-mapped paths)."""
    icj = model.ImplicitCollectionJobs()
    icj.tool_execution_state_id = None
    job = model.Job()
    job.tool_execution_state_id = 7
    assoc = model.ImplicitCollectionJobsJobAssociation()
    assoc.job = job
    icj.jobs = [assoc]

    icj.__strict_check_before_flush__()
