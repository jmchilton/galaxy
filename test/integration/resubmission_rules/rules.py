from galaxy.jobs import JobDestination

DEFAULT_INITIAL_DESTINATION = "fail_first_try"


def initial_destination(resource_params):
    return resource_params.get("initial_destination", None) or DEFAULT_INITIAL_DESTINATION


def dynamic_resubmit_once(resource_params):
    job_destination = JobDestination()
    job_destination['resubmit'] = [dict(
        condition="any_failure",
        destination="local",
    )]
    job_destination['runner'] = "failure_runner"
    return job_destination
