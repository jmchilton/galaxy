import type { WorkflowRunModel } from "./model";

/** Why the simple run form can't run a workflow; ``WorkflowRunForm`` explains each one. */
export type SimpleFormDisabledReason =
    | "hasWorkflowResourceParameters"
    | "hasDisconnectedInputs"
    | "hasReplacementParameters";

/** Why the simple form can't run this workflow, if it can't. The first reason found is the one shown. */
export function simpleFormDisabledReason(model: WorkflowRunModel): SimpleFormDisabledReason | undefined {
    // Just render the whole form for resource request parameters (kind of
    // niche - I'm not sure anyone is using these currently anyway).
    if (model.hasWorkflowResourceParameters) {
        return "hasWorkflowResourceParameters";
    }
    // If there are required parameters in a tool form (a disconnected runtime
    // input), we have to render the tool form steps and cannot use the
    // simplified tool form.
    if (model.hasOpenToolSteps) {
        return "hasDisconnectedInputs";
    }
    // These only work with PJA - the API doesn't evaluate them at
    // all outside that context currently. The main workflow form renders
    // these dynamically and takes care of all the validation and setup details
    // on the frontend. If these are implemented on the backend at some
    // point this restriction can be lifted.
    if (model.hasReplacementParametersInToolForm) {
        return "hasReplacementParameters";
    }
    return undefined;
}
