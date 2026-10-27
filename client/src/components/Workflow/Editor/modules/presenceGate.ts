/** Step-level presence gating: writing a gate for an input and deciding whether a step's `when` guards it. */

import {
    normalizeConnectionOutputLinks,
    type Step,
    stepOutputCanBeAbsent,
    type WorkflowStepStore,
} from "@/stores/workflowStepStore";

import { expressionGuardsInputPresence, expressionReferencesInput, presenceGateExpression } from "./whenExpression";
import { resolveConnectionNameToInputPath } from "./workflowInputPath";

/** The output a connection would come from. */
export interface ConnectionSource {
    stepId: number;
    name: string;
}

/** The `when` that runs `step` only while `inputName` is provided, or null when its path is ambiguous. */
export function presenceGateForStepInput(step: Step, inputName: string): string | null {
    const inputPath = resolveConnectionNameToInputPath(inputName, step.tool_state);
    return inputPath ? presenceGateExpression(inputPath) : null;
}

/** True when `inputName` may arrive empty and a presence gate can be written for it. */
export function canGateOnInput(step: Step, inputName: string, stepStore: WorkflowStepStore): boolean {
    return connectedInputCanBeAbsent(step, inputName, stepStore) && Boolean(presenceGateForStepInput(step, inputName));
}

/** True when every source of this input is optional or on a gated step. */
function connectedInputCanBeAbsent(step: Step, inputName: string, stepStore: WorkflowStepStore): boolean {
    const links = normalizeConnectionOutputLinks(step.input_connections?.[inputName]);
    return (
        links.length > 0 &&
        links.every((link) => {
            const sourceStep = stepStore.getStep(link.id);
            return sourceStep ? stepOutputCanBeAbsent(sourceStep, link.output_name) : false;
        })
    );
}

/**
 * True when the step's `when` lets `inputName` be absent; `source` enables the twin dispatch check.
 * Hand-written gates are accepted unless known to run while the input is absent.
 */
export function stepGatesInputPresence(step: Step, inputName: string, source?: ConnectionSource): boolean {
    if (!step.when) {
        return false;
    }
    const inputPath = resolveConnectionNameToInputPath(inputName, step.tool_state);
    if (!inputPath) {
        return false;
    }
    if (!step.inputs?.some((input) => input.name === inputName)) {
        // A synthesized gate port feeds nothing, so an inverse gate is as valid as a positive one.
        return expressionReferencesInput(step.when, inputPath);
    }
    if (expressionGuardsInputPresence(step.when, inputPath)) {
        return true;
    }
    return source ? gatedThroughSharedSource(step, inputName, source) : false;
}

/** Twin dispatch: the gate guards another input fed solely by `source`, so both are absent together. */
function gatedThroughSharedSource(step: Step, inputName: string, source: ConnectionSource): boolean {
    return Object.entries(step.input_connections ?? {}).some(([name, links]) => {
        const inputPath = resolveConnectionNameToInputPath(name, step.tool_state);
        if (name === inputName || !inputPath || !expressionGuardsInputPresence(step.when, inputPath)) {
            return false;
        }
        const linkArray = normalizeConnectionOutputLinks(links);
        // A second source could keep the probe present while `source` is absent.
        return (
            linkArray.length === 1 && linkArray[0]!.id === source.stepId && linkArray[0]!.output_name === source.name
        );
    });
}
