import { matchCase } from "@/components/Form/utilities";

/** Scalar parameter types the simple run form can expose. */
const EXPOSABLE_TYPES = new Set(["text", "integer", "float", "boolean", "select", "color"]);

export interface StepParameterNode {
    id: string;
    kind: "step" | "subworkflow" | "section" | "repeat" | "instance" | "conditional" | "leaf";
    label: string;
    /** Exposure key ``<step_index>|<prefixed name>`` of a leaf. */
    key?: string;
    /** Set on leaves and conditional test params shown but not selectable. */
    disabledReason?: string;
    /** Set on subworkflow steps, whose parameters the graph picker can't pick. */
    lockedReason?: string;
    /** Value the workflow sets, for leaves and conditional test params. */
    value?: string;
    help?: string;
    /** Breadcrumb from the step down to this leaf, for card titles. */
    path?: string[];
    input?: any;
    children: StepParameterNode[];
}

export const CONDITIONAL_LOCKED_REASON =
    "Changing this would change which parameters below apply. Set it in the expanded form.";

/** Display text of an input's value (option labels for selects); undefined when empty. */
export function displayValue(input: any): string | undefined {
    const raw = Array.isArray(input.value) ? input.value : [input.value];
    const parts = raw
        .filter((v: unknown) => v !== null && v !== undefined && v !== "")
        .map((v: unknown) => {
            const option = (input.options || []).find((o: any[]) => String(o[1]) === String(v));
            return option ? String(option[0]) : String(v);
        });
    return parts.length ? parts.join(", ") : undefined;
}

function leafDisabledReason(input: any, context: Record<string, any>): string | undefined {
    if (input.is_dynamic || (input.data_ref && context[input.data_ref])) {
        return "Options depend on a data input";
    }
    if (!EXPOSABLE_TYPES.has(input.type)) {
        return `${input.type} parameters are not supported yet`;
    }
    return undefined;
}

function walk(inputs: any[], stepIndex: number, prefix: string, path: string[], idPrefix: string): StepParameterNode[] {
    const context: Record<string, any> = {};
    for (const input of inputs) {
        context[input.name] = input;
    }
    const nodes: StepParameterNode[] = [];
    for (const input of inputs) {
        const name = prefix ? `${prefix}|${input.name}` : input.name;
        const label = input.label || input.title || input.name;
        const id = `${idPrefix}/${input.name}`;
        if (input.type === "repeat") {
            const instances = (input.cache || []).map((cache: any[], j: number) => {
                const instanceLabel = `${input.title || input.name} ${j + 1}`;
                return {
                    id: `${id}_${j}`,
                    kind: "instance",
                    label: instanceLabel,
                    children: walk(cache, stepIndex, `${name}_${j}`, [...path, instanceLabel], `${id}_${j}`),
                } as StepParameterNode;
            });
            nodes.push({ id, kind: "repeat", label, children: instances });
        } else if (input.type === "section") {
            nodes.push({
                id,
                kind: "section",
                label,
                children: walk(input.inputs || [], stepIndex, name, [...path, label], id),
            });
        } else if (input.type === "conditional") {
            const testParam = input.test_param;
            const caseIndex = matchCase(input, testParam.value);
            const activeInputs = caseIndex >= 0 ? input.cases[caseIndex].inputs : [];
            nodes.push({
                id,
                kind: "conditional",
                label: testParam.label || input.name,
                value: displayValue(testParam),
                disabledReason: CONDITIONAL_LOCKED_REASON,
                help: testParam.help || undefined,
                children: walk(activeInputs, stepIndex, name, [...path, label], id),
            });
        } else if (input.type === "data" || input.type === "data_collection" || input.type === "hidden") {
            // Data and connected inputs (the run model hides those) are never exposed.
            continue;
        } else if (input.wp_linked) {
            continue;
        } else {
            nodes.push({
                id,
                kind: "leaf",
                label,
                key: `${stepIndex}|${name}`,
                disabledReason: leafDisabledReason(input, context),
                value: displayValue(input),
                help: input.help || undefined,
                path: [...path, label],
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

export const SUBWORKFLOW_LOCKED_REASON = "Parameters inside subworkflows can't be picked from the graph";

/** Steps → parameters tree of a ``WorkflowRunModel`` for picking step parameters to expose. */
export function buildStepParameterTree(model: { steps: any[] }): StepParameterNode[] {
    const tree: StepParameterNode[] = [];
    for (const step of model.steps) {
        const stepLabel = `Step ${step.step_index + 1}: ${step.step_label || step.step_name}`;
        if (step.step_type === "subworkflow") {
            const id = String(step.step_index);
            tree.push({
                id,
                kind: "subworkflow",
                label: stepLabel,
                lockedReason: SUBWORKFLOW_LOCKED_REASON,
                children: [],
            });
            continue;
        }
        if (step.step_type !== "tool") {
            continue;
        }
        const children = walk(step.inputs || [], step.step_index, "", [stepLabel], `${step.step_index}`);
        tree.push({ id: String(step.step_index), kind: "step", label: stepLabel, children });
    }
    return tree;
}

export function treeLeaves(nodes: StepParameterNode[]): StepParameterNode[] {
    return nodes.flatMap((node) => (node.kind === "leaf" ? [node] : treeLeaves(node.children)));
}

/** Copy of ``nodes`` keeping leaves whose label path matches ``query`` and dropping empty branches. */
export function filterTree(nodes: StepParameterNode[], query: string): StepParameterNode[] {
    const q = query.trim().toLowerCase();
    if (!q) {
        return nodes;
    }
    const keep = (node: StepParameterNode, ancestorMatch: boolean): StepParameterNode | null => {
        const match = ancestorMatch || node.label.toLowerCase().includes(q) || Boolean(node.key?.includes(q));
        if (node.kind === "leaf") {
            return match ? node : null;
        }
        const children = node.children.map((child) => keep(child, match)).filter(Boolean) as StepParameterNode[];
        return children.length ? { ...node, children } : null;
    };
    return nodes.map((node) => keep(node, false)).filter(Boolean) as StepParameterNode[];
}

export interface ResolvedExposures {
    leaves: StepParameterNode[];
    dropped: DroppedExposure[];
}

export interface DroppedExposure {
    key: string;
    reason: string;
    /** Inside a subworkflow: the graph picker can't show or remove it. */
    locked?: boolean;
}

/** Resolve exposure keys against the tree, in workflow order, dropping unknown or unexposable ones. */
export function resolveExposureKeys(tree: StepParameterNode[], keys: string[]): ResolvedExposures {
    const byKey = new Map(treeLeaves(tree).map((leaf) => [leaf.key as string, leaf]));
    const wanted = new Set<string>();
    const locked = new Map(
        tree.filter((node) => node.lockedReason).map((node) => [node.id, node.lockedReason as string]),
    );
    const dropped: DroppedExposure[] = [];
    for (const key of keys) {
        const leaf = byKey.get(key);
        const lockedReason = locked.get(key.split("|")[0] as string);
        if (lockedReason) {
            dropped.push({ key, reason: lockedReason, locked: true });
        } else if (!leaf) {
            dropped.push({ key, reason: "no such parameter in the workflow's current state" });
        } else if (leaf.disabledReason) {
            dropped.push({ key, reason: leaf.disabledReason });
        } else {
            wanted.add(key);
        }
    }
    const leaves = treeLeaves(tree).filter((leaf) => wanted.has(leaf.key as string));
    return { leaves, dropped };
}

/** ``parameters`` request dict (``{"<step_index>": {"<rest>": value}}``) from exposure key values. */
export function exposedParametersPayload(values: Record<string, unknown>): Record<string, Record<string, unknown>> {
    const parameters: Record<string, Record<string, unknown>> = {};
    for (const [key, value] of Object.entries(values)) {
        const [stepIndex, ...rest] = key.split("|");
        (parameters[stepIndex as string] ||= {})[rest.join("|")] = value;
    }
    return parameters;
}

/** Value a rerun request recorded for an exposure key, if any. */
export function rerunStepParameterValue(
    parameters: Record<string, Record<string, unknown>> | null | undefined,
    key: string,
): unknown {
    const [stepIndex, ...rest] = key.split("|");
    return parameters?.[stepIndex as string]?.[rest.join("|")];
}

/** Does a rerun request carry step parameters it did not record as exposed? */
export function rerunHasUnexposedStepParameters(
    request:
        | { parameters?: Record<string, Record<string, unknown>> | null; exposed_step_parameters?: string[] | null }
        | undefined,
): boolean {
    if (!request?.parameters) {
        return false;
    }
    const exposed = new Set(request.exposed_step_parameters || []);
    return Object.entries(request.parameters).some(([stepIndex, params]) =>
        Object.keys(params || {}).some((name) => !exposed.has(`${stepIndex}|${name}`)),
    );
}

/** Parse ``step_param_value`` query entries ``<key>=<value>``. */
export function parseStepParamValues(entries: string[]): Record<string, string> {
    const values: Record<string, string> = {};
    for (const entry of entries) {
        const at = entry.indexOf("=");
        if (at > 0) {
            values[entry.slice(0, at)] = entry.slice(at + 1);
        }
    }
    return values;
}

/** Keys added to and removed from ``current`` by a picked set. */
export function diffExposures(current: string[], picked: Set<string>): { added: string[]; removed: string[] } {
    const before = new Set(current);
    return {
        added: [...picked].filter((key) => !before.has(key)),
        removed: current.filter((key) => !picked.has(key)),
    };
}
