"""The module defines the stock Galaxy workflow scheduling plugin.

Currently, this plugin simply schedules as much of the workflow as is possible.
"""
import time

from galaxy.work import context

from galaxy.workflow import run
from galaxy.workflow import run_request
from galaxy.workflow import modules

from ..schedulers import ActiveWorkflowSchedulingPlugin

import logging
log = logging.getLogger( __name__ )


class CoreWorkflowSchedulingPlugin( ActiveWorkflowSchedulingPlugin ):
    """Stock workflow scheduling plugin."""

    plugin_type = "core"

    def __init__( self, **kwds ):

        def int_or_none(val):
            return int(val) if val is not None else None

        self.steps_per_iteration = int_or_none(kwds.get("steps_per_iteration", None))
        self.jobs_per_iteration = int_or_none(kwds.get("jobs_per_iteration", None))
        self.time_per_iteration = int_or_none(kwds.get("time_per_iteration", None))

    def startup( self, app ):
        self.app = app

    def shutdown( self ):
        pass

    def schedule( self, workflow_invocation ):
        workflow = workflow_invocation.workflow
        history = workflow_invocation.history
        request_context = context.WorkRequestContext(
            app=self.app,
            history=history,
            user=history.user
        )  # trans-like object not tied to a web-thread.
        workflow_run_config = run_request.workflow_request_to_run_config(
            request_context,
            workflow_invocation
        )
        run.schedule(
            trans=request_context,
            workflow=workflow,
            workflow_run_config=workflow_run_config,
            workflow_invocation=workflow_invocation,
        )

    def check_progress(self, workflow_progress):
        if self.steps_per_iteration is not None:
            if workflow_progress.iteration_step_count > self.steps_per_iteration:
                raise modules.DelayedWorkflowEvaluation()

        if self.jobs_per_iteration is not None:
            if workflow_progress.iteration_job_count > self.jobs_per_iteration:
                raise modules.DelayedWorkflowEvaluation()

        if self.time_per_iteration:
            if (time.time() - workflow_progress.iteration_start_time) > self.time_per_iteration:
                raise modules.DelayedWorkflowEvaluation()


__all__ = [ 'CoreWorkflowSchedulingPlugin' ]
