from galaxy.jobs.runners.pulsar import PulsarEmbeddedMQJobRunner


class LosesFirstCompleteStatusJobRunner(PulsarEmbeddedMQJobRunner):
    """Drops the first complete status update of each job, as if the message was lost."""

    def __init__(self, *args, **kwds):
        super().__init__(*args, **kwds)
        self._dropped_complete_job_ids = set()
        self.finished_job_ids = []

    def _update_job_state_for_status(self, job_state, pulsar_status, full_status=None):
        if pulsar_status == "complete" and job_state.job_id not in self._dropped_complete_job_ids:
            self._dropped_complete_job_ids.add(job_state.job_id)
            return None
        return super()._update_job_state_for_status(job_state, pulsar_status, full_status=full_status)

    def finish_job(self, job_state):
        self.finished_job_ids.append(job_state.job_wrapper.job_id)
        super().finish_job(job_state)
