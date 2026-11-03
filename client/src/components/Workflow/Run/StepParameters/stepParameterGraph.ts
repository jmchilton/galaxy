import { faCheckCircle } from "@fortawesome/free-solid-svg-icons";

import { isWorkflowInput } from "@/components/Workflow/constants";
import { getHeaderClass, type GraphStep } from "@/composables/useInvocationGraph";
import type { Step } from "@/stores/workflowStepStore";

import { type StepParameterNode, treeLeaves } from "./stepParameterTree";

export type StepParameterGraphStep = Step & Pick<GraphStep, "nodeText" | "headerClass" | "headerIcon">;

/** Selectable parameters under ``node`` (a tool step, or every tool step inside a subworkflow) and how many are picked. */
export function pickedParameterCounts(node: StepParameterNode, picked: Set<string>) {
    const selectable = treeLeaves([node]).filter((leaf) => !leaf.disabledReason);
    return {
        picked: selectable.filter((leaf) => picked.has(leaf.id)).length,
        selectable: selectable.length,
    };
}

function parameterCount(count: number): string {
    return `${count} parameter${count === 1 ? "" : "s"}`;
}

/**
 * Workflow editor steps annotated with how many of each step's parameters are picked, for a read-only graph.
 *
 * Graph step ids are step indexes, the ids of the tree's top-level nodes. Input steps are left as they are.
 */
export function stepParameterGraphSteps(
    steps: Record<string, Step>,
    tree: StepParameterNode[],
    picked: Set<string>,
): Record<string, StepParameterGraphStep> {
    const nodes = new Map(tree.map((node) => [node.id, node]));
    const result: Record<string, StepParameterGraphStep> = {};
    for (const [id, step] of Object.entries(steps)) {
        if (isWorkflowInput(step.type)) {
            result[id] = step;
            continue;
        }
        const node = nodes.get(String(step.id));
        const counts = node ? pickedParameterCounts(node, picked) : { picked: 0, selectable: 0 };
        let nodeText = "No parameters to choose";
        if (counts.picked) {
            nodeText = `<b>${counts.picked}</b> of ${parameterCount(counts.selectable)} chosen`;
        } else if (counts.selectable) {
            nodeText = `${parameterCount(counts.selectable)} to choose from`;
        }
        result[id] = {
            ...step,
            nodeText,
            headerClass: counts.picked ? getHeaderClass("ok") : undefined,
            headerIcon: counts.picked ? faCheckCircle : undefined,
        };
    }
    return result;
}
