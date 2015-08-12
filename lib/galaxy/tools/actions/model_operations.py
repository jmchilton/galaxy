from galaxy.tools.actions import (
    DefaultToolAction,
    OutputCollections,
)
from galaxy.util.odict import odict

import logging
log = logging.getLogger( __name__ )


class ModelOperationToolAction( DefaultToolAction ):

    def check_inputs_ready( self, tool, trans, incoming, history ):
        history, inp_data, inp_dataset_collections = self._collect_inputs(tool, trans, incoming, history)

        tool.check_inputs_ready( inp_data, inp_dataset_collections )

    def execute( self, tool, trans, incoming={}, set_output_hid=False, overwrite=True, history=None, job_params=None, mapping_over_collection=False, **kwargs ):
        history, inp_data, inp_dataset_collections = self._collect_inputs(tool, trans, incoming, history)

        # Build name for output datasets based on tool name and input names
        on_text = self._get_on_text( inp_data )

        # wrapped params are used by change_format action and by output.label; only perform this wrapping once, as needed
        wrapped_params = self._wrapped_params( trans, tool, incoming )

        out_data = odict()
        output_collections = OutputCollections(
            trans,
            history,
            tool=tool,
            tool_action=self,
            mapping_over_collection=mapping_over_collection,
            on_text=on_text,
            incoming=incoming,
            params=wrapped_params.params,
            job_params=job_params,
        )

        #
        # Create job.
        #
        job, galaxy_session = self._new_job_for_session( trans, tool, history )
        self._produce_outputs( trans, tool, out_data, output_collections, incoming=incoming, history=history )
        self._record_inputs( trans, tool, job, incoming, inp_data, inp_dataset_collections )
        self._record_outputs( job, out_data, output_collections )
        start_job_state = job.state
        job.state = job.states.OK
        trans.sa_session.add( job )
        trans.sa_session.flush()  # ensure job.id are available

        #
        # Setup job and job wrapper.
        #
        job.state = start_job_state  # job inputs have been configured, restore initial job state
        # job.set_handler(tool.get_job_handler(None))
        trans.sa_session.flush()

        # Queue the job for execution
        # trans.app.job_queue.put( job.id, tool.id )
        # trans.log_event( "Added database job action to the job queue, id: %s" % str(job.id), tool_id=job.tool_id )
        log.info("Calling produce_outputs, tool is %s" % tool)
        return job, out_data

    def _produce_outputs( self, trans, tool, out_data, output_collections, incoming, history, **kwargs ):
        tool.produce_outputs( trans, out_data, output_collections, incoming, history=history )
        for output in out_data.values():
            trans.sa_session.add( output )
        trans.sa_session.flush()
