import type { FormInputNode } from "@/components/Form/composables/useFormState";
import { buildNestedState, matchCase } from "@/components/Form/utilities";

import { parameterKey, type ParameterPath } from "./stepParameterOverrides";

/** A tool input of the run form data. */
export type ToolInput = FormInputNode & {
    /** Section and repeat title */
    title?: string;
    is_dynamic?: boolean;
    /** Name of the data input a data-dependent parameter reads its options from */
    data_ref?: string;
};

/** Scalar parameter types the simple run form can expose. */
const EXPOSABLE_TYPES = new Set(["text", "integer", "float", "boolean", "select", "color"]);

/**
 * Node ids are the path from the outermost step down to the node, joined by ``/``, so a leaf's id is its key in
 * ``step_parameter_overrides``, e.g. ``2/queries/1/column``.
 */
interface StepParameterNodeBase {
    id: string;
    label: string;
    children: StepParameterNode[];
}

/** A node that only groups those below it. */
export interface StepParameterGroup extends StepParameterNodeBase {
    kind: "step" | "subworkflow" | "section" | "repeat" | "instance";
}

/** A row the picker shows with the value the workflow sets: a conditional's test parameter, or a parameter. */
interface StepParameterRow extends StepParameterNodeBase {
    /** Why the row can't be picked. */
    disabledReason?: string;
    /** Value the workflow sets */
    value?: string;
    help?: string;
}

/** A conditional, shown as its test parameter - locked - over the parameters of its active case. */
export interface StepParameterConditional extends StepParameterRow {
    kind: "conditional";
    disabledReason: string;
}

/** A parameter that can be picked, or a locked one shown in the picker. */
export interface StepParameterLeaf extends StepParameterRow {
    kind: "leaf";
    /** Step indexes, outermost first, and the parameter's path in that step's tool state. */
    stepPath: number[];
    paramPath: ParameterPath;
    /** Breadcrumb from the step down to this leaf, for card titles. */
    path: string[];
    input: ToolInput;
    children: [];
}

export type StepParameterNode = StepParameterGroup | StepParameterConditional | StepParameterLeaf;

export const CONDITIONAL_LOCKED_REASON =
    "Changing this would change which parameters below apply. Set it in the expanded form.";

export function isLeaf(node: StepParameterNode): node is StepParameterLeaf {
    return node.kind === "leaf";
}

/** Display text of an input's value (option labels for selects); undefined when empty. */
export function displayValue(input: Pick<ToolInput, "value" | "options">): string | undefined {
    const raw: unknown[] = Array.isArray(input.value) ? input.value : [input.value];
    const options = Array.isArray(input.options) ? input.options : [];
    const parts = raw
        .filter((v) => v !== null && v !== undefined && v !== "")
        .map((v) => {
            const option = options.find((o) => Array.isArray(o) && String(o[1]) === String(v));
            return Array.isArray(option) ? String(option[0]) : String(v);
        });
    return parts.length ? parts.join(", ") : undefined;
}

function leafDisabledReason(input: ToolInput, context: Record<string, ToolInput>): string | undefined {
    if (input.is_dynamic || (input.data_ref && context[input.data_ref])) {
        return "Options depend on a data input";
    }
    if (!EXPOSABLE_TYPES.has(input.type)) {
        return `${input.type} parameters are not supported yet`;
    }
    return undefined;
}

function isConnected(input: ToolInput): boolean {
    // Connected inputs of outer steps are hidden by the run model, those of inner steps keep their marker.
    return input.type === "hidden" || input.value?.__class__ === "ConnectedValue";
}

function walk(
    inputs: ToolInput[],
    stepPath: number[],
    paramPath: ParameterPath,
    breadcrumb: string[],
    idPrefix: string,
): StepParameterNode[] {
    const context: Record<string, ToolInput> = {};
    for (const input of inputs) {
        context[input.name] = input;
    }
    const nodes: StepParameterNode[] = [];
    for (const input of inputs) {
        const label = input.label || input.title || input.name;
        const id = `${idPrefix}/${input.name}`;
        const inputPath = [...paramPath, input.name];
        if (input.type === "repeat") {
            const instances = (input.cache || []).map((cache, j): StepParameterNode => {
                const instanceLabel = `${input.title || input.name} ${j + 1}`;
                return {
                    id: `${id}/${j}`,
                    kind: "instance",
                    label: instanceLabel,
                    children: walk(cache, stepPath, [...inputPath, j], [...breadcrumb, instanceLabel], `${id}/${j}`),
                };
            });
            nodes.push({ id, kind: "repeat", label, children: instances });
        } else if (input.type === "section") {
            nodes.push({
                id,
                kind: "section",
                label,
                children: walk(input.inputs || [], stepPath, inputPath, [...breadcrumb, label], id),
            });
        } else if (input.type === "conditional" && input.test_param) {
            const testParam = input.test_param;
            const caseIndex = matchCase(input, testParam.value);
            const activeInputs = input.cases?.[caseIndex]?.inputs ?? [];
            const conditionalLabel = testParam.label || input.name;
            nodes.push({
                id,
                kind: "conditional",
                label: conditionalLabel,
                value: displayValue(testParam),
                disabledReason: CONDITIONAL_LOCKED_REASON,
                help: testParam.help || undefined,
                children: walk(activeInputs, stepPath, inputPath, [...breadcrumb, conditionalLabel], id),
            });
        } else if (input.type === "data" || input.type === "data_collection" || isConnected(input)) {
            // Data inputs and connected parameters are never exposed.
            continue;
        } else if (input.wp_linked) {
            continue;
        } else {
            nodes.push({
                id,
                kind: "leaf",
                label,
                stepPath,
                paramPath: inputPath,
                disabledReason: leafDisabledReason(input, context),
                value: displayValue(input),
                help: input.help || undefined,
                path: [...breadcrumb, label],
                input,
                children: [],
            });
        }
    }
    return nodes;
}

export function hasSelectableLeaf(node: StepParameterNode): boolean {
    return node.kind === "leaf" ? !node.disabledReason : node.children.some(hasSelectableLeaf);
}

/** A step of a ``WorkflowRunModel``. */
export interface RunStep {
    step_index: number;
    step_type: string;
    step_label?: string | null;
    step_name?: string;
    inputs?: ToolInput[];
    /** Tool and subworkflow steps of a subworkflow step, as the run data lists them. */
    subworkflow_steps?: RunStep[];
}

/**
 * Step nodes, labelled ``Step N: name``. Steps inside subworkflows count from 1 again, so their labels lead with
 * the enclosing subworkflows' names (``QC › Step 2: name``), and their leaves' breadcrumbs start from that label.
 */
function stepNodes(steps: RunStep[], parentPath: number[], scope: string[]): StepParameterNode[] {
    const nodes: StepParameterNode[] = [];
    for (const step of steps) {
        const stepPath = [...parentPath, step.step_index];
        const id = parameterKey(stepPath);
        const name = step.step_label || step.step_name || "";
        const label = [...scope, `Step ${step.step_index + 1}: ${name}`].join(" › ");
        if (step.step_type === "tool") {
            const children = walk(step.inputs || [], stepPath, [], [label], id);
            nodes.push({ id, kind: "step", label, children });
        } else if (step.step_type === "subworkflow") {
            const children = stepNodes(step.subworkflow_steps || [], stepPath, [...scope, name]);
            nodes.push({ id, kind: "subworkflow", label, children });
        }
    }
    return nodes;
}

/** Steps → parameters tree of a ``WorkflowRunModel``, subworkflows included, for picking step parameters. */
export function buildStepParameterTree(model: { steps: RunStep[] }): StepParameterNode[] {
    return stepNodes(model.steps, [], []);
}

export function treeLeaves(nodes: StepParameterNode[]): StepParameterLeaf[] {
    return nodes.flatMap((node) => (isLeaf(node) ? [node] : treeLeaves(node.children)));
}

/** Copy of ``nodes`` keeping leaves whose label path matches ``query`` and dropping empty branches. */
export function filterTree(nodes: StepParameterNode[], query: string): StepParameterNode[] {
    const q = query.trim().toLowerCase();
    if (!q) {
        return nodes;
    }
    const keep = (node: StepParameterNode, ancestorMatch: boolean): StepParameterNode | null => {
        const match = ancestorMatch || node.label.toLowerCase().includes(q);
        if (node.kind === "leaf") {
            return match ? node : null;
        }
        const children = node.children.flatMap((child) => keep(child, match) ?? []);
        return children.length ? { ...node, children } : null;
    };
    return nodes.flatMap((node) => keep(node, false) ?? []);
}

export interface DroppedStepParameter {
    key: string;
    /** The key in the picker's labels, e.g. ``Step 3: echo › Filter type › pattern`` */
    label: string;
    reason: string;
}

export interface ResolvedStepParameters {
    leaves: StepParameterLeaf[];
    dropped: DroppedStepParameter[];
}

/**
 * Label of a parameter key, also one the workflow doesn't have: the labels of the tree nodes it reaches,
 * then its remaining segments, steps counted from 1.
 */
export function stepParameterKeyLabel(tree: StepParameterNode[], key: string): string {
    const segments = key.split("/");
    let labels: string[] = [];
    let nodes = tree;
    let last: StepParameterNode | undefined;
    let matched = 0;
    for (; matched < segments.length; matched++) {
        const id = parameterKey(segments.slice(0, matched + 1));
        const node = nodes.find((child) => child.id === id);
        if (!node) {
            break;
        }
        if (node.kind === "step" || node.kind === "subworkflow") {
            // Step labels carry the subworkflows they are in.
            labels = [node.label];
        } else if (node.kind !== "repeat") {
            labels.push(node.label);
        }
        last = node;
        nodes = node.children;
    }
    const rest = segments.slice(matched);
    const [next] = rest;
    if (next !== undefined && /^\d+$/.test(next)) {
        if (!last || last.kind === "subworkflow") {
            rest[0] = `Step ${Number(next) + 1}`;
        } else if (last.kind === "repeat") {
            rest[0] = `${last.label} ${Number(next) + 1}`;
        }
    }
    return [...labels, ...rest].join(" › ");
}

/** Resolve leaf keys against the tree, in workflow order, dropping unknown or unexposable ones. */
export function resolveStepParameterKeys(tree: StepParameterNode[], keys: string[]): ResolvedStepParameters {
    const leaves = treeLeaves(tree);
    const byKey = new Map(leaves.map((leaf) => [leaf.id, leaf]));
    const wanted = new Set<string>();
    const dropped: DroppedStepParameter[] = [];
    for (const key of keys) {
        const leaf = byKey.get(key);
        if (!leaf) {
            dropped.push({
                key,
                label: stepParameterKeyLabel(tree, key),
                reason: "no such parameter in the workflow's current state",
            });
        } else if (leaf.disabledReason) {
            dropped.push({ key, label: stepParameterKeyLabel(tree, key), reason: leaf.disabledReason });
        } else {
            wanted.add(key);
        }
    }
    return { leaves: leaves.filter((leaf) => wanted.has(leaf.id)), dropped };
}

/** Typed value of a card's form value, as the tool's own form would send it. */
export function typedParameterValue(input: ToolInput, value: unknown): unknown {
    return (buildNestedState([input], { [input.name]: value }) as Record<string, unknown>)[input.name];
}
