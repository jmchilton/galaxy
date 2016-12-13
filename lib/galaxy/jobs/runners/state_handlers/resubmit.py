import logging

__all__ = ('failure', )

log = logging.getLogger(__name__)

from galaxy.jobs.runners import JobState
from ._safe_eval import safe_eval


MESSAGES = dict(
    walltime_reached='it reached the walltime',
    memory_limit_reached='it exceeded the amount of allocated memory',
    unknown_error='it encountered an unknown error'
)


def eval_condition(condition, job_state):
    runner_state = getattr(job_state, 'runner_state', None) or JobState.runner_states.UNKNOWN_ERROR
    if (runner_state not in (JobState.runner_states.WALLTIME_REACHED,
                             JobState.runner_states.MEMORY_LIMIT_REACHED,
                             JobState.runner_states.UNKNOWN_ERROR)):
        # not set or not a handleable runner state
        return False

    condition_locals = {
        "walltime_reached": runner_state == JobState.runner_states.WALLTIME_REACHED,
        "memory_limit_reached": runner_state == JobState.runner_states.MEMORY_LIMIT_REACHED,
        "unknown_error": JobState.runner_states.UNKNOWN_ERROR,
        "any_failure": True,
        "any_potential_job_failure": True,  # Add a hook here - later on allow tools to describe things that are definitely input problems.
        "attempt": job_state.job_wrapper.get_job().attempt,
    }

    # Small optimization to eliminate the need to parse AST and eval for simple variables.
    if condition in condition_locals:
        return condition_locals[condition]
    else:
        return safe_eval(condition, condition_locals)


def failure(app, job_runner, job_state):
    runner_state = getattr(job_state, 'runner_state', None) or JobState.runner_states.UNKNOWN_ERROR
    # Intercept jobs that hit the walltime and have a walltime or
    # nonspecific resubmit destination configured
    for resubmit in job_state.job_destination.get('resubmit'):
        condition = resubmit.get('condition', None)
        if condition and not eval_condition(condition, job_state):
            # There is a resubmit defined for the destination but
            # its condition is not for the encountered state
            continue

        external_id = getattr(job_state, "job_id", None)
        if external_id:
            job_log_prefix = "(%s/%s)" % (job_state.job_wrapper.job_id, job_state.job_id)
        else:
            job_log_prefix = "(%s)" % (job_state.job_wrapper.job_id)

        destination = resubmit['destination']
        log.info("%s Job will be resubmitted to '%s' because %s at "
                 "the '%s' destination",
                 job_log_prefix,
                 destination,
                 MESSAGES[runner_state],
                 job_state.job_wrapper.job_destination.id )
        # fetch JobDestination for the id or tag
        if destination:
            new_destination = app.job_config.get_destination(destination)
        else:
            new_destination = job_state.job_destination

        # Resolve dynamic if necessary
        new_destination = (job_state.job_wrapper.job_runner_mapper
                           .cache_job_destination(new_destination))
        # Reset job state
        job_state.job_wrapper.clear_working_directory()
        job_state.job_wrapper.invalidate_external_metadata()
        job = job_state.job_wrapper.get_job()
        if resubmit.get('handler', None):
            log.debug('%s Job reassigned to handler %s',
                      job_log_prefix,
                      resubmit['handler'])
            job.set_handler(resubmit['handler'])
            job_runner.sa_session.add( job )
            # Is this safe to do here?
            job_runner.sa_session.flush()
        # Cache the destination to prevent rerunning dynamic after
        # resubmit
        job_state.job_wrapper.job_runner_mapper \
            .cached_job_destination = new_destination
        job_state.job_wrapper.set_job_destination(new_destination)
        # Clear external ID (state change below flushes the change)
        job.job_runner_external_id = None
        # Allow the UI to query for resubmitted state
        if job.params is None:
            job.params = {}
        job_state.runner_state_handled = True
        info = "This job was resubmitted to the queue because %s on its " \
               "compute resource." % MESSAGES[runner_state]
        job_runner.mark_as_resubmitted(job_state, info=info)
        return
