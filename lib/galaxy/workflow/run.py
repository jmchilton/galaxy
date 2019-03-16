import logging
import os
import uuid

from galaxy import model
from galaxy.util import ExecutionTimer
from galaxy.util.odict import odict
from galaxy.workflow import modules
from galaxy.workflow.run_request import (
    workflow_request_to_run_config,
    workflow_run_config_to_request,
    WorkflowRunConfig
)


log = logging.getLogger(__name__)


# Entry point for direct invoke via controllers. Deprecated to some degree.
def invoke(trans, workflow, workflow_run_config, workflow_invocation=None, populate_state=False):
    if force_queue(trans, workflow):
        invocation = queue_invoke(trans, workflow, workflow_run_config, populate_state=populate_state)
        return [], invocation
    else:
        return __invoke(trans, workflow, workflow_run_config, workflow_invocation, populate_state)


# Entry point for core workflow scheduler.
def schedule(trans, workflow, workflow_run_config, workflow_invocation):
    return __invoke(trans, workflow, workflow_run_config, workflow_invocation)


BASIC_WORKFLOW_STEP_TYPES = [None, "tool", "data_input", "data_collection_input"]


def force_queue(trans, workflow):
    # Default behavior is still to just schedule workflows completley right
    # away. This can be modified here in various ways.

    # TODO: check for implicit connections - these should also force backgrounding
    #       this would fix running Dan's data manager workflows via UI.
    # TODO: ensure state if populated before calling force_queue from old API
    #       workflow endpoint so the has_module check below is unneeded and these
    #       interesting workflows will work with the older endpoint.
    config = trans.app.config
    force_for_collection = config.force_beta_workflow_scheduled_for_collections
    force_min_steps = config.force_beta_workflow_scheduled_min_steps

    step_count = len(workflow.steps)
    if step_count > force_min_steps:
        log.info("Workflow has many steps %d, backgrounding execution" % step_count)
        return True
    for step in workflow.steps:
        # State and module haven't been populated if workflow submitted via
        # the API. API requests for "interesting" workflows should use newer
        # endpoint that skips this check entirely - POST /api/workflows/<id>/invocations
        has_module = hasattr(step, "module")
        if step.type not in BASIC_WORKFLOW_STEP_TYPES:
            log.info("Found non-basic workflow step type - backgrounding execution")
            # Force all new beta modules types to be use force queueing of
            # workflow.
            return True
        if step.type == "data_collection_input" and force_for_collection:
            log.info("Found collection input step - backgrounding execution")
            return True
        if step.type == "tool" and has_module and step.module.tool.produces_collections_with_unknown_structure:
            log.info("Found dynamically structured output collection - backgrounding execution")
            return True
    return False


def __invoke(trans, workflow, workflow_run_config, workflow_invocation=None, populate_state=False):
    """ Run the supplied workflow in the supplied target_history.
    """
    if populate_state:
        modules.populate_module_and_state(trans, workflow, workflow_run_config.param_map, allow_tool_state_corrections=workflow_run_config.allow_tool_state_corrections)

    invoker = WorkflowInvoker(
        trans,
        workflow,
        workflow_run_config,
        workflow_invocation=workflow_invocation,
    )
    try:
        outputs = invoker.invoke()
    except modules.CancelWorkflowEvaluation:
        if workflow_invocation:
            if workflow_invocation.cancel():
                trans.sa_session.add(workflow_invocation)
        outputs = []
    except Exception:
        log.exception("Failed to execute scheduled workflow.")
        if workflow_invocation:
            # Running workflow invocation in background, just mark
            # persistent workflow invocation as failed.
            workflow_invocation.fail()
            trans.sa_session.add(workflow_invocation)
        else:
            # Running new transient workflow invocation in legacy
            # controller action - propage the exception up.
            raise
        outputs = []

    if workflow_invocation:
        # Be sure to update state of workflow_invocation.
        trans.sa_session.flush()

    return outputs, invoker.workflow_invocation


def queue_invoke(trans, workflow, workflow_run_config, request_params={}, populate_state=True):
    if populate_state:
        modules.populate_module_and_state(trans, workflow, workflow_run_config.param_map, allow_tool_state_corrections=workflow_run_config.allow_tool_state_corrections)
    workflow_invocation = workflow_run_config_to_request(trans, workflow_run_config, workflow)
    workflow_invocation.workflow = workflow
    return trans.app.workflow_scheduling_manager.queue(workflow_invocation, request_params)


class WorkflowInvoker(object):

    def __init__(self, trans, workflow, workflow_run_config, workflow_invocation=None, progress=None):
        self.trans = trans
        self.workflow = workflow
        if progress is not None:
            assert workflow_invocation is None
            workflow_invocation = progress.workflow_invocation

        if workflow_invocation is None:
            invocation_uuid = uuid.uuid1()

            workflow_invocation = model.WorkflowInvocation()
            workflow_invocation.workflow = self.workflow

            # In one way or another, following attributes will become persistent
            # so they are available during delayed/revisited workflow scheduling.
            workflow_invocation.uuid = invocation_uuid
            workflow_invocation.history = workflow_run_config.target_history

            self.workflow_invocation = workflow_invocation
        else:
            self.workflow_invocation = workflow_invocation

        self.workflow_invocation.copy_inputs_to_history = workflow_run_config.copy_inputs_to_history
        self.workflow_invocation.use_cached_job = workflow_run_config.use_cached_job
        self.workflow_invocation.replacement_dict = workflow_run_config.replacement_dict

        module_injector = modules.WorkflowModuleInjector(trans)
        if progress is None:
            progress = WorkflowProgress(
                self.workflow_invocation,
                workflow_run_config.inputs,
                module_injector,
                param_map=workflow_run_config.param_map,
                jobs_per_scheduling_iteration=getattr(trans.app.config, "maximum_workflow_jobs_per_scheduling_iteration", -1),
            )
        self.progress = progress

    def invoke(self):
        workflow_invocation = self.workflow_invocation
        config = self.trans.app.config
        maximum_duration = getattr(config, "maximum_workflow_invocation_duration", -1)
        if maximum_duration > 0 and workflow_invocation.seconds_since_created > maximum_duration:
            log.debug("Workflow invocation [%s] exceeded maximum number of seconds allowed for scheduling [%s], failing." % (workflow_invocation.id, maximum_duration))
            workflow_invocation.state = model.WorkflowInvocation.states.FAILED
            # All jobs ran successfully, so we can save now
            self.trans.sa_session.add(workflow_invocation)

            # Not flushing in here, because web controller may create multiple
            # invocations.
            return self.progress.outputs

        if workflow_invocation.history.deleted:
            log.info("Cancelled workflow evaluation due to deleted history")
            raise modules.CancelWorkflowEvaluation()

        remaining_steps = self.progress.remaining_steps()
        delayed_steps = False
        for (step, workflow_invocation_step) in remaining_steps:
            step_delayed = False
            step_timer = ExecutionTimer()
            try:
                self.__check_implicitly_dependent_steps(step)

                if not workflow_invocation_step:
                    workflow_invocation_step = model.WorkflowInvocationStep()
                    workflow_invocation_step.workflow_invocation = workflow_invocation
                    workflow_invocation_step.workflow_step = step
                    workflow_invocation_step.state = 'new'

                    workflow_invocation.steps.append(workflow_invocation_step)

                incomplete_or_none = self._invoke_step(workflow_invocation_step)
                if incomplete_or_none is False:
                    step_delayed = delayed_steps = True
                    workflow_invocation_step.state = 'ready'
                    self.progress.mark_step_outputs_delayed(step, why="Not all jobs scheduled for state.")
                else:
                    workflow_invocation_step.state = 'scheduled'
            except modules.DelayedWorkflowEvaluation as de:
                step_delayed = delayed_steps = True
                self.progress.mark_step_outputs_delayed(step, why=de.why)
            except Exception:
                log.exception(
                    "Failed to schedule %s, problem occurred on %s.",
                    self.workflow_invocation.workflow.log_str(),
                    step.log_str(),
                )
                raise

            if not step_delayed:
                log.debug("Workflow step %s of invocation %s invoked %s" % (step.id, workflow_invocation.id, step_timer))

        if delayed_steps:
            state = model.WorkflowInvocation.states.READY
        else:
            state = model.WorkflowInvocation.states.SCHEDULED
        workflow_invocation.state = state

        # All jobs ran successfully, so we can save now
        self.trans.sa_session.add(workflow_invocation)

        # Not flushing in here, because web controller may create multiple
        # invocations.
        return self.progress.outputs

    def __check_implicitly_dependent_steps(self, step):
        """ Method will delay the workflow evaluation if implicitly dependent
        steps (steps dependent but not through an input->output way) are not
        yet complete.
        """
        for input_connection in step.input_connections:
            if input_connection.non_data_connection:
                output_id = input_connection.output_step.id
                self.__check_implicitly_dependent_step(output_id)

    def __check_implicitly_dependent_step(self, output_id):
        step_invocation = self.workflow_invocation.step_invocation_for_step_id(output_id)

        # No steps created yet - have to delay evaluation.
        if not step_invocation:
            delayed_why = "depends on step [%s] but that step has not been invoked yet" % output_id
            raise modules.DelayedWorkflowEvaluation(why=delayed_why)

        if step_invocation.state != 'scheduled':
            delayed_why = "depends on step [%s] job has not finished scheduling yet" % output_id
            raise modules.DelayedWorkflowEvaluation(delayed_why)

        for job_assoc in step_invocation.jobs:
            job = job_assoc.job
            if job:
                # At least one job in incomplete.
                if not job.finished:
                    delayed_why = "depends on step [%s] but one or more jobs created from that step have not finished yet" % output_id
                    raise modules.DelayedWorkflowEvaluation(why=delayed_why)

                if job.state != job.states.OK:
                    raise modules.CancelWorkflowEvaluation()

            else:
                # TODO: Handle implicit dependency on stuff like
                # pause steps.
                pass

    def _invoke_step(self, invocation_step):
        incomplete_or_none = invocation_step.workflow_step.module.execute(self.trans,
                                                                          self.progress,
                                                                          invocation_step,
                                                                          use_cached_job=self.workflow_invocation.use_cached_job)
        return incomplete_or_none


STEP_OUTPUT_DELAYED = object()


class WorkflowProgress(object):

    def __init__(self, workflow_invocation, inputs_by_step_id, module_injector, param_map, workflow_mapping_structure=None, jobs_per_scheduling_iteration=-1):
        self.outputs = odict()
        self.module_injector = module_injector
        self.workflow_invocation = workflow_invocation
        self.inputs_by_step_id = inputs_by_step_id
        self.param_map = param_map
        self.jobs_per_scheduling_iteration = jobs_per_scheduling_iteration
        self.jobs_scheduled_this_iteration = 0
        self.workflow_mapping_structure = workflow_mapping_structure

    @property
    def maximum_jobs_to_schedule_or_none(self):
        if self.jobs_per_scheduling_iteration > 0:
            return self.jobs_per_scheduling_iteration - self.jobs_scheduled_this_iteration
        else:
            return None

    @property
    def trans(self):
        return self.module_injector.trans

    def record_executed_job_count(self, job_count):
        self.jobs_scheduled_this_iteration += job_count

    def remaining_steps(self):
        # Previously computed and persisted step states.
        step_states = self.workflow_invocation.step_states_by_step_id()
        steps = self.workflow_invocation.workflow.steps

        # TODO: Wouldn't a generator be much better here so we don't have to reason about
        # steps we are no where near ready to schedule?
        remaining_steps = []
        step_invocations_by_id = self.workflow_invocation.step_invocations_by_step_id()
        for step in steps:
            step_id = step.id
            if not hasattr(step, 'module'):
                self.module_injector.inject(step, step_args=self.param_map.get(step.id, {}))
                if step_id not in step_states:
                    template = "Workflow invocation [%s] has no step state for step id [%s]. States ids are %s."
                    message = template % (self.workflow_invocation.id, step_id, list(step_states.keys()))
                    raise Exception(message)
                runtime_state = step_states[step_id].value
                step.state = step.module.decode_runtime_state(runtime_state)

            invocation_step = step_invocations_by_id.get(step_id, None)
            if invocation_step and invocation_step.state == 'scheduled':
                self._recover_mapping(invocation_step)
            else:
                remaining_steps.append((step, invocation_step))
        return remaining_steps

    def replacement_for_input_connections(self, step, input_dict, connections):
        replacement = modules.NO_REPLACEMENT

        prefixed_name = input_dict["name"]
        step_input = step.inputs_by_name.get(prefixed_name, None)

        merge_type = model.WorkflowStepInput.default_merge_type
        if step_input:
            merge_type = step_input.merge_type

        is_data = input_dict["input_type"] in ["dataset", "dataset_collection"]
        if len(connections) == 1:
            replacement = self.replacement_for_connection(connections[0], is_data=is_data)
        else:
            # We've mapped multiple individual inputs to a single parameter,
            # promote output to a collection.
            inputs = []
            input_history_content_type = None
            input_collection_type = None
            for i, c in enumerate(connections):
                input_from_connection = self.replacement_for_connection(c, is_data=is_data)
                is_data = hasattr(input_from_connection, "history_content_type")
                if is_data:
                    input_history_content_type = input_from_connection.history_content_type
                    if i == 0:
                        if input_history_content_type == "dataset_collection":
                            input_collection_type = input_from_connection.collection.collection_type
                        else:
                            input_collection_type = None
                    else:
                        if input_collection_type is None:
                            if input_history_content_type != "dataset":
                                raise Exception("Cannot map over a combination of datasets and collections.")
                        else:
                            if input_history_content_type != "dataset_collection":
                                raise Exception("Cannot merge over combinations of datasets and collections.")
                            elif input_from_connection.collection.collection_type != input_collection_type:
                                raise Exception("Cannot merge collections of different collection types.")

                inputs.append(input_from_connection)

            if input_dict["input_type"] == "dataset_collection":
                # TODO: Implement more nested types here...
                assert input_dict["collection_types"] == ["list"], input.collection_types

            collection = model.DatasetCollection()
            # If individual datasets provided (type is None) - premote to a list.
            collection.collection_type = input_collection_type or "list"
            elements = []

            next_index = 0
            if input_collection_type is None:

                if merge_type == "merge_nested":
                    raise NotImplementedError()

                for input in inputs:
                    element = model.DatasetCollectionElement(
                        element=input,
                        element_index=next_index,
                        element_identifier=str(next_index),
                    )
                    elements.append(element)
                    next_index += 1

            elif input_collection_type == "list":
                if merge_type == "merge_flattened":
                    for input in inputs:
                        for dataset_instance in input.dataset_instances:
                            element = model.DatasetCollectionElement(
                                element=dataset_instance,
                                element_index=next_index,
                                element_identifier=str(next_index),
                            )
                            elements.append(element)
                            next_index += 1
                elif merge_type == "merge_nested":
                    # Increase nested level of collection
                    collection.collection_type = "list:%s" % input_collection_type
                    for input in inputs:
                        element = model.DatasetCollectionElement(
                            element=input.collection,
                            element_index=next_index,
                            element_identifier=str(next_index),
                        )
                        elements.append(element)
                        next_index += 1
            else:
                raise NotImplementedError()

            collection.elements = elements

            ephemeral_collection = modules.EphemeralCollection(
                collection=collection,
                history=self.workflow_invocation.history,
            )
            replacement = ephemeral_collection

        return replacement

    def replacement_for_input(self, step, input_dict):
        replacement = modules.NO_REPLACEMENT
        prefixed_name = input_dict["name"]
        multiple = input_dict["multiple"]
        if prefixed_name in step.input_connections_by_name:
            connection = step.input_connections_by_name[prefixed_name]
            if input_dict["input_type"] == "dataset" and multiple:
                replacement = [self.replacement_for_connection(c) for c in connection]
                # If replacement is just one dataset collection, replace tool
                # input_dict with dataset collection - tool framework will extract
                # datasets properly.
                if len(replacement) == 1:
                    if isinstance(replacement[0], model.HistoryDatasetCollectionAssociation):
                        replacement = replacement[0]
            else:
                replacement = self.replacement_for_input_connections(
                    step, input_dict, connection,
                )

        return replacement

    def replacement_for_connection(self, connection, is_data=True):
        output_step_id = connection.output_step.id
        if output_step_id not in self.outputs:
            template = "No outputs found for step id %s, outputs are %s"
            message = template % (output_step_id, self.outputs)
            raise Exception(message)
        step_outputs = self.outputs[output_step_id]
        if step_outputs is STEP_OUTPUT_DELAYED:
            delayed_why = "dependent step [%s] delayed, so this step must be delayed" % output_step_id
            raise modules.DelayedWorkflowEvaluation(why=delayed_why)
        output_name = connection.output_name
        try:
            replacement = step_outputs[output_name]
        except KeyError:
            # Must resolve.
            template = "Workflow evaluation problem - failed to find output_name %s in step_outputs %s"
            message = template % (output_name, step_outputs)
            raise Exception(message)
        if isinstance(replacement, model.HistoryDatasetCollectionAssociation):
            if not replacement.collection.populated:
                if not replacement.collection.waiting_for_elements:
                    # If we are not waiting for elements, there was some
                    # problem creating the collection. Collection will never
                    # be populated.
                    # TODO: consider distinguish between cancelled and failed?
                    raise modules.CancelWorkflowEvaluation()

                delayed_why = "dependent collection [%s] not yet populated with datasets" % replacement.id
                raise modules.DelayedWorkflowEvaluation(why=delayed_why)

        is_hda = isinstance(replacement, model.HistoryDatasetAssociation)
        is_hdca = isinstance(replacement, model.HistoryDatasetCollectionAssociation)
        if not is_data and (is_hda or is_hdca):
            dataset_instances = []
            if is_hda:
                dataset_instances = [replacement]
            else:
                dataset_instances = replacement.dataset_instances

            for dataset_instance in dataset_instances:
                if dataset_instance.is_pending:
                    raise modules.DelayedWorkflowEvaluation()
                elif not dataset_instance.is_ok:
                    raise modules.CancelWorkflowEvaluation()

        return replacement

    def get_replacement_workflow_output(self, workflow_output):
        step = workflow_output.workflow_step
        output_name = workflow_output.output_name
        step_outputs = self.outputs[step.id]
        if step_outputs is STEP_OUTPUT_DELAYED:
            delayed_why = "depends on workflow output [%s] but that output has not been created yet" % output_name
            raise modules.DelayedWorkflowEvaluation(why=delayed_why)
        else:
            return step_outputs[output_name]

    def raw_to_galaxy(self, as_dict_value):
        trans = self.trans
        app = trans.app
        history = self.workflow_invocation.history

        from galaxy.tools.cwl.util import abs_path
        relative_to = "/"  # TODO
        path = abs_path(as_dict_value.get("location"), relative_to)

        name = os.path.basename(path)
        primary_data = model.HistoryDatasetAssociation(
            name=name,
            extension="data",  # TODO: cwl default...
            designation=None,
            visible=True,
            dbkey="?",
            create_dataset=True,
            flush=False,
            sa_session=trans.sa_session
        )
        log.info("path is %s" % path)
        primary_data.link_to(path)
        permissions = app.security_agent.history_get_default_permissions(history)
        app.security_agent.set_all_dataset_permissions(primary_data.dataset, permissions, new=True, flush=False)
        trans.sa_session.add(primary_data)
        trans.sa_session.flush()
        history.add_dataset(primary_data)
        primary_data.init_meta()
        primary_data.set_meta()
        primary_data.set_peek()
        primary_data.raw_set_dataset_state('ok')
        trans.sa_session.flush()
        return primary_data

    def set_outputs_for_input(self, invocation_step, outputs=None):
        step = invocation_step.workflow_step

        if outputs is None:
            outputs = {}

        if self.inputs_by_step_id:
            step_id = step.id
            if step_id not in self.inputs_by_step_id and 'output' not in outputs:
                default_value = step.input_default_value
                if default_value:
                    outputs['output'] = default_value
                else:
                    template = "Step with id %s not found in inputs_step_id (%s)"
                    message = template % (step.log_str(), self.inputs_by_step_id)
                    raise ValueError(message)
            elif step_id in self.inputs_by_step_id:
                outputs['output'] = self.inputs_by_step_id[step_id]

        output = outputs.get('output')
        # TODO: handle extra files and directory types and collections and all the stuff...
        if output and isinstance(output, dict) and output.get("class") == "File":
            primary_data = self.raw_to_galaxy(output)
            outputs['output'] = primary_data

        log.info("outputs are")
        log.info(outputs)
        self.set_step_outputs(invocation_step, outputs)

    def set_step_outputs(self, invocation_step, outputs, already_persisted=False):
        step = invocation_step.workflow_step
        self.outputs[step.id] = outputs
        if not already_persisted:
            for output_name, output_object in outputs.items():
                if hasattr(output_object, "history_content_type"):
                    invocation_step.add_output(output_name, output_object)
                else:
                    # This is a problem, this non-data, non-collection output
                    # won't be recovered on a subsequent workflow scheduling
                    # iteration. This seems to have been a pre-existing problem
                    # prior to #4584 though.
                    pass
            for workflow_output in step.workflow_outputs:
                output_name = workflow_output.output_name
                if output_name not in outputs:
                    message = "Failed to find expected workflow output [%s] in step outputs [%s]" % (output_name, outputs)
                    # raise KeyError(message)
                    # Pre-18.01 we would have never even detected this output wasn't configured
                    # and even in 18.01 we don't have a way to tell the user something bad is
                    # happening so I guess we just log a debug message and continue sadly for now.
                    # Once https://github.com/galaxyproject/galaxy/issues/5142 is complete we could
                    # at least tell the user what happened, give them a warning.
                    log.debug(message)
                    continue
                output = outputs[output_name]
                self._record_workflow_output(
                    step,
                    workflow_output,
                    output=output,
                )

    def _record_workflow_output(self, step, workflow_output, output):
        self.workflow_invocation.add_output(workflow_output, step, output)

    def mark_step_outputs_delayed(self, step, why=None):
        if why:
            message = "Marking step %s outputs of invocation %s delayed (%s)" % (step.id, self.workflow_invocation.id, why)
            log.debug(message)
        self.outputs[step.id] = STEP_OUTPUT_DELAYED

    def _subworkflow_invocation(self, step):
        workflow_invocation = self.workflow_invocation
        subworkflow_invocation = workflow_invocation.get_subworkflow_invocation_for_step(step)
        if subworkflow_invocation is None:
            raise Exception("Failed to find persisted workflow invocation for step [%s]" % step.id)
        return subworkflow_invocation

    def subworkflow_invoker(self, trans, step, structure, use_cached_job=False):
        subworkflow_invocation = self._subworkflow_invocation(step)
        workflow_run_config = workflow_request_to_run_config(trans, subworkflow_invocation)
        subworkflow_progress = self.subworkflow_progress(subworkflow_invocation, step, workflow_run_config.param_map, structure)
        subworkflow_invocation = subworkflow_progress.workflow_invocation
        return WorkflowInvoker(
            trans,
            workflow=subworkflow_invocation.workflow,
            workflow_run_config=workflow_run_config,
            progress=subworkflow_progress,
        )

    def subworkflow_progress(self, subworkflow_invocation, step, param_map, structure):
        subworkflow = subworkflow_invocation.workflow
        subworkflow_inputs = {}
        for input_subworkflow_step in subworkflow.input_steps:
            subworkflow_step_id = input_subworkflow_step.id
            connections = []
            for input_connection in step.input_connections:
                if input_connection.input_subworkflow_step == input_subworkflow_step:
                    connections.append(input_connection)

            if not connections:
                raise Exception("Could not find connections for all subworkflow inputs.")

            replacement = self.replacement_for_input_connections(
                step,
                dict(
                    name=input_subworkflow_step.label,  # TODO: only module knows this unfortunately
                    input_type=input_subworkflow_step.input_type,
                ),
                connections,
            )
            subworkflow_inputs[subworkflow_step_id] = replacement

        return WorkflowProgress(
            subworkflow_invocation,
            subworkflow_inputs,
            self.module_injector,
            param_map=param_map,
            workflow_mapping_structure=structure,
        )

    def _recover_mapping(self, step_invocation):
        try:
            step_invocation.workflow_step.module.recover_mapping(step_invocation, self)
        except modules.DelayedWorkflowEvaluation as de:
            self.mark_step_outputs_delayed(step_invocation.workflow_step, de.why)


__all__ = ('invoke', 'WorkflowRunConfig')
