"""Red-green tests for the "ICJ supersedes child Job/WIS" invariant
enforced by ``__strict_check_before_flush__`` on ``Job``,
``WorkflowInvocationStep``, and ``ImplicitCollectionJobs``.

The invariant: when an ICJ carries a ``tool_execution_state_id``, its
constituent Jobs and parent WIS must NOT carry their own direct TES
FK — the ICJ is the canonical anchor for the mapped execution event.
Outside the ICJ case (standalone Job, WIS without ICJ), the direct FK
is canonical. ToolRequest and Job co-pointing at the same TES is fine
and not the subject of this invariant.

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


def test_wis_with_icj_and_tes_fk_raises():
    wis = model.WorkflowInvocationStep()
    wis.implicit_collection_jobs_id = 3
    wis.tool_execution_state_id = 7

    with pytest.raises(Exception, match="implicit_collection_jobs_id and also"):
        wis.__strict_check_before_flush__()


def test_wis_with_icj_without_tes_fk_passes():
    wis = model.WorkflowInvocationStep()
    wis.implicit_collection_jobs_id = 3

    wis.__strict_check_before_flush__()


def test_wis_without_icj_with_tes_fk_passes():
    """Failure-capture or non-mapped step: no ICJ, WIS carries TES
    directly. Allowed."""
    wis = model.WorkflowInvocationStep()
    wis.tool_execution_state_id = 7

    wis.__strict_check_before_flush__()


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
