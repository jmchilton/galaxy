"""
Once state information has been calculated, handle actually executing tools
from various states, tracking results, and building implicit dataset
collections from matched collections.
"""
import collections
import logging
from threading import Thread

from six.moves.queue import Queue

from galaxy.tools.actions import on_text_for_names, ToolExecutionCache
from galaxy.tools.parser import ToolOutputCollectionPart
from galaxy.util import ExecutionTimer

log = logging.getLogger( __name__ )

EXECUTION_SUCCESS_MESSAGE = "Tool [%s] created job [%s] %s"


def execute( trans, tool, param_combinations, history, rerun_remap_job_id=None, collection_info=None, workflow_invocation_uuid=None ):
    """
    Execute a tool and return object containing summary (output data, number of
    failures, etc...).
    """
    all_jobs_timer = ExecutionTimer()
    execution_tracker = ToolExecutionTracker( tool, param_combinations, collection_info )
    app = trans.app
    execution_cache = ToolExecutionCache(trans)

    def execute_single_job(params):
        job_timer = ExecutionTimer()
        if workflow_invocation_uuid:
            params[ '__workflow_invocation_uuid__' ] = workflow_invocation_uuid
        elif '__workflow_invocation_uuid__' in params:
            # Only workflow invocation code gets to set this, ignore user supplied
            # values or rerun parameters.
            del params[ '__workflow_invocation_uuid__' ]
        job, result = tool.handle_single_execution( trans, rerun_remap_job_id, params, history, collection_info, execution_cache )
        if job:
            message = EXECUTION_SUCCESS_MESSAGE % (tool.id, job.id, job_timer)
            log.debug(message)
            execution_tracker.record_success( job, result )
        else:
            execution_tracker.record_error( result )

    config = app.config
    burst_at = getattr( config, 'tool_submission_burst_at', 10 )
    burst_threads = getattr( config, 'tool_submission_burst_threads', 1 )

    tool_action = tool.tool_action
    if hasattr( tool_action, "check_inputs_ready" ):
        for params in execution_tracker.param_combinations:
            # This will throw an exception if the tool is not ready.
            tool_action.check_inputs_ready(
                tool,
                trans,
                params,
                history
            )

    job_count = len(execution_tracker.param_combinations)
    if job_count < burst_at or burst_threads < 2:
        for params in execution_tracker.param_combinations:
            execute_single_job(params)
    else:
        q = Queue()

        def worker():
            while True:
                params = q.get()
                execute_single_job(params)
                q.task_done()

        for i in range(burst_threads):
            t = Thread(target=worker)
            t.daemon = True
            t.start()

        for params in execution_tracker.param_combinations:
            q.put(params)

        q.join()

    log.debug("Executed %d job(s) for tool %s request: %s" % (job_count, tool.id, all_jobs_timer))
    if collection_info:
        history = history or tool.get_default_history_by_trans( trans )
        if len(param_combinations) == 0:
            template = "Attempting to map over an empty collection, this is not yet implemented. collection_info is [%s]"
            message = template % collection_info
            log.warn(message)
            raise Exception(message)
        params = param_combinations[0]
        execution_tracker.create_output_collections( trans, history, params )

    return execution_tracker


class ExecutionTracker( object ):

    def __init__( self, collection_info ):
        self.collection_info = collection_info
        self.successful_executions = []
        self.failed_executions = 0
        self.execution_errors = []
        self.outputs_by_output_name = collections.defaultdict(list)
        self.implicit_collections = {}

    def create_output_collections( self, trans, history, params ):
        # TODO: Move this function - it doesn't belong here but it does need
        # the information in this class and potential extensions.
        if self.failed_executions > 0:
            return []

        structure = self.collection_info.structure

        output_namer = self.get_output_namer( trans, history, params )

        collections = {}

        implicit_inputs = self.collection_info.implicit_inputs
        for output_name, outputs in self.outputs_by_output_name.items():
            if not len( structure ) == len( outputs ):
                # Output does not have the same structure, if all jobs were
                # successfully submitted this shouldn't have happened.
                log.warning( "Problem matching up datasets while attempting to create implicit dataset collections")
                continue
            element_identifiers = self.element_identifiers( trans, output_name, outputs )

            implicit_collection_info = dict(
                implicit_inputs=implicit_inputs,
                implicit_output_name=output_name,
                outputs=outputs
            )

            output_collection_name = output_namer( output_name )
            child_element_identifiers = element_identifiers[ "element_identifiers" ]
            collection_type = element_identifiers[ "collection_type" ]
            collection = trans.app.dataset_collections_service.create(
                trans=trans,
                parent=history,
                name=output_collection_name,
                element_identifiers=child_element_identifiers,
                collection_type=collection_type,
                implicit_collection_info=implicit_collection_info,
            )
            for job_or_invocation in self.successful_executions:
                # TODO: Think through this, may only want this for output
                # collections - or we may be already recording data in some
                # other way.
                if job_or_invocation not in trans.sa_session:
                    job = trans.sa_session.query( job_or_invocation.__class__ ).get( job_or_invocation.id )
                job.add_output_dataset_collection( output_name, collection )
            collections[ output_name ] = collection

        # Needed to flush the association created just above with
        # job.add_output_dataset_collection.
        trans.sa_session.flush()
        self.implicit_collections = collections

    def element_identifiers( self, trans, output_name, outputs ):
        structure = self.collection_info.structure

        output = self.get_output_by_name( output_name )

        element_identifiers = None
        if hasattr(output, "default_identifier_source"):
            # Switch the structure for outputs if the output specified a default_identifier_source
            collection_type_descriptions = trans.app.dataset_collections_service.collection_type_descriptions

            source_collection = self.collection_info.collections.get(output.default_identifier_source)
            if source_collection:
                collection_type_description = collection_type_descriptions.for_collection_type(source_collection.collection.collection_type)
                _structure = structure.for_dataset_collection( source_collection.collection, collection_type_description=collection_type_description)
                if structure.can_match(_structure):
                    element_identifiers = _structure.element_identifiers_for_outputs(trans, outputs)

        if not element_identifiers:
            element_identifiers = structure.element_identifiers_for_outputs( trans, outputs )

        return element_identifiers


class InvocationExecutionTracker( ExecutionTracker ):

    def __init__( self, invocation, collection_info ):
        super( ToolExecutionTracker, self ).__init__( collection_info )
        self.invocation = invocation

    def record_success( self, invocation ):
        self.successful_executions.append( invocation )

        for output_dataset_assoc in invocation.output_datasets:
            label = output_dataset_assoc.workflow_output.label
            self.outputs_by_output_name[ label ].append( output_dataset_assoc.dataset )
        for output_dataset_collection_instance_assoc in invocation.output_dataset_collections:
            label = output_dataset_assoc.workflow_output.label
            self.outputs_by_output_name[ label ].append( output_dataset_assoc.dataset_collection )

    def get_output_by_name( self, name ):
        return self.invocation.workflow.get_workflow_output( name )

    def get_output_namer( self, trans, history, params ):
        return lambda name: name

    def record_error( self, error ):
        self.failed_executions += 1
        message = "There was a failure executing workflow invocation [%s] - %s"
        log.warning(message, self.invocation.id, error)
        self.execution_errors.append( error )


class ToolExecutionTracker( ExecutionTracker ):

    def __init__( self, tool, param_combinations, collection_info ):
        super( ToolExecutionTracker, self ).__init__( collection_info )
        self.tool = tool
        self.param_combinations = param_combinations
        self.output_datasets = []
        self.output_collections = []

    def record_success( self, job, outputs ):
        self.successful_executions.append( job )
        self.output_datasets.extend( outputs )
        for output_name, output_dataset in outputs:
            if ToolOutputCollectionPart.is_named_collection_part_name( output_name ):
                # Skip known collection outputs, these will be covered by
                # output collections.
                continue
            self.outputs_by_output_name[ output_name ].append( output_dataset )
        for job_output in job.output_dataset_collections:
            self.outputs_by_output_name[ job_output.name ].append( job_output.dataset_collection )
        for job_output in job.output_dataset_collection_instances:
            self.output_collections.append( ( job_output.name, job_output.dataset_collection_instance ) )

    def record_error( self, error ):
        self.failed_executions += 1
        message = "There was a failure executing a job for tool [%s] - %s"
        log.warning(message, self.tool.id, error)
        self.execution_errors.append( error )

    def get_output_by_name( self, name ):
        output = self.tool.outputs[ name ]
        return output

    def get_output_namer( self, trans, history, params ):
        if not self.collection_info.uses_ephemeral_collections:
            # params is just one sample tool param execution with parallelized
            # collection replaced with a specific dataset. Need to replace this
            # with the collection and wrap everything up so can evaluate output
            # label.
            params.update( self.collection_info.collections )  # Replace datasets with source collections for labelling outputs.

            collection_names = ["collection %d" % c.hid for c in self.collection_info.collections.values()]
            on_text = on_text_for_names( collection_names )
        else:
            on_text = "implicitly created collection from inputs"

        def get_output_name( output_name ):
            output = self.get_output_by_name( output_name )
            try:
                output_collection_name = self.tool.tool_action.get_output_name(
                    output,
                    dataset=None,
                    tool=self.tool,
                    on_text=on_text,
                    trans=trans,
                    history=history,
                    params=params,
                    incoming=None,
                    job_params=None,
                )
            except Exception:
                output_collection_name = "%s across %s" % ( self.tool.name, on_text )

            return output_collection_name

        return get_output_name


__all__ = ( 'execute', )
