import { isPlainObject } from "./stepParameterOverrides";
import { stepParameterKeyLabel, type StepParameterNode } from "./stepParameterTree";

/** An error a rejected invocation request gave for a step parameter. */
export interface StepParameterError {
    /** The parameter's key in ``step_parameter_overrides``, e.g. ``2/cond/min`` */
    key: string;
    /** The key in the picker's labels */
    label: string;
    message: string;
}

function nodesById(nodes: StepParameterNode[], byId = new Map<string, StepParameterNode>()) {
    for (const node of nodes) {
        byId.set(node.id, node);
        nodesById(node.children, byId);
    }
    return byId;
}

/** The key of a tool step's flat parameter name (``queries_1|column_name`` → ``2/queries/1/column_name``). */
function flatNameKey(nodes: Map<string, StepParameterNode>, stepKey: string, flatName: string): string {
    let key = stepKey;
    for (const segment of flatName.split("|")) {
        const instance = /^(.+)_(\d+)$/.exec(segment);
        if (!nodes.has(`${key}/${segment}`) && instance && nodes.get(`${key}/${instance[1]}`)?.kind === "repeat") {
            key = `${key}/${instance[1]}/${instance[2]}`;
        } else {
            key = `${key}/${segment}`;
        }
    }
    return key;
}

/**
 * The step parameter errors in the ``err_data`` of a rejected invocation request - none if it isn't keyed by step.
 *
 * Validating ``step_parameter_overrides`` keys an error by its path (``{"2/cond/pattern": "..."}``). Computing a
 * step's runtime state keys errors by step index, nested by inner step index for steps inside subworkflows, and then
 * by flat parameter name (``{"1": {"1": {"cond|min": "..."}}}``).
 */
export function stepParameterErrors(tree: StepParameterNode[], errData: unknown): StepParameterError[] {
    const entries = isPlainObject(errData) ? Object.entries(errData) : [];
    if (!entries.every(([key]) => /^\d+(\/|$)/.test(key))) {
        return [];
    }
    const nodes = nodesById(tree);
    const errors: StepParameterError[] = [];
    const add = (key: string, message: unknown) => {
        if (isPlainObject(message)) {
            Object.entries(message).forEach(([name, inner]) => add(`${key}/${name}`, inner));
        } else {
            errors.push({ key, label: stepParameterKeyLabel(tree, key), message: String(message) });
        }
    };
    const visitStep = (stepKey: string, stepErrors: unknown) => {
        if (!isPlainObject(stepErrors)) {
            add(stepKey, stepErrors);
            return;
        }
        const isSubworkflow = nodes.get(stepKey)?.kind === "subworkflow";
        for (const [name, error] of Object.entries(stepErrors)) {
            if (isSubworkflow) {
                visitStep(`${stepKey}/${name}`, error);
            } else {
                add(flatNameKey(nodes, stepKey, name), error);
            }
        }
    };
    for (const [key, error] of entries) {
        if (key.includes("/")) {
            add(key, error);
        } else {
            visitStep(key, error);
        }
    }
    return errors;
}

export interface StepParameterSubmissionErrors {
    /** Errors for the parameters shown as cards, by key */
    cards: Record<string, string>;
    /** The submission alert's message, listing the errors no card shows */
    message: string;
}

/** Split the errors of a rejected invocation request between the cards of ``shownKeys`` and the submission alert. */
export function stepParameterSubmissionErrors(
    tree: StepParameterNode[],
    shownKeys: Iterable<string>,
    errData: unknown,
    errMsg: string,
): StepParameterSubmissionErrors {
    const shown = new Set(shownKeys);
    const cards: Record<string, string> = {};
    const other: StepParameterError[] = [];
    for (const error of stepParameterErrors(tree, errData)) {
        if (shown.has(error.key)) {
            cards[error.key] = cards[error.key] ? `${cards[error.key]} ${error.message}` : error.message;
        } else {
            other.push(error);
        }
    }
    const details = other.map((error) => `${error.label} - ${error.message}`).join("; ");
    if (!Object.keys(cards).length) {
        return { cards, message: details ? `${errMsg}: ${details}` : errMsg };
    }
    const summary = details ? `${errMsg}: ${details}` : "Some step parameters are not valid";
    const sentence = /[.!?]$/.test(summary) ? summary : `${summary}.`;
    return { cards, message: `${sentence} Fix the step parameters marked below.` };
}
