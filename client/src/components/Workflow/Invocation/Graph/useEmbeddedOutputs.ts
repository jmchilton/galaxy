import { computed, nextTick, type Ref, ref, watch } from "vue";

import {
    type EmbeddedNodeRequest,
    type LayoutEdge,
    layoutEmbeddedOutputs,
    type LayoutNode,
    type LayoutRect,
    type NudgeDirection,
} from "@/components/Workflow/Editor/modules/embeddedOutputLayout";
import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useWorkflowStores } from "@/composables/workflowStores";

export const EMBEDDED_OUTPUT_WIDTH = 360;
export const EMBEDDED_OUTPUT_HEIGHT = 260;

export interface EmbeddedOutput {
    key: string;
    label: string;
    sourceId: number;
    item: InvocationOutputItem;
    rect: LayoutRect;
}

type StepPosition = NonNullable<GraphStep["position"]>;

/** Workflow outputs that have produced a dataset/collection, keyed for the layout */
function collectRequests(steps: Record<string, GraphStep>) {
    const requests: (EmbeddedNodeRequest & { label: string; item: InvocationOutputItem })[] = [];
    for (const step of Object.values(steps)) {
        for (const workflowOutput of step.workflow_outputs ?? []) {
            const item = step.outputItems?.[workflowOutput.output_name];
            if (!workflowOutput.label || !item) {
                continue;
            }
            requests.push({
                key: `${step.id}-${workflowOutput.output_name}`,
                label: workflowOutput.label,
                sourceId: step.id,
                item,
                width: EMBEDDED_OUTPUT_WIDTH,
                height: EMBEDDED_OUTPUT_HEIGHT,
            });
        }
    }
    return requests;
}

function collectEdges(steps: Record<string, GraphStep>): LayoutEdge[] {
    const edges: LayoutEdge[] = [];
    for (const step of Object.values(steps)) {
        for (const connection of Object.values(step.input_connections ?? {})) {
            const connections = Array.isArray(connection) ? connection : [connection];
            for (const c of connections) {
                if (c) {
                    edges.push({ from: c.id, to: step.id });
                }
            }
        }
    }
    return edges;
}

/** Turns workflow outputs into large embedded nodes on the invocation graph, nudging steps to make room. */
export function useEmbeddedOutputs(
    storeId: string,
    steps: Ref<Record<string, GraphStep>>,
    enabled: Ref<boolean>,
    direction: Ref<NudgeDirection>,
) {
    const { stateStore, stepStore } = useWorkflowStores(storeId);

    const originalPositions = new Map<number, StepPosition>();
    const embedded = ref<EmbeddedOutput[]>([]);
    const maxDisplacement = ref(0);

    const requestKeys = computed(() =>
        collectRequests(steps.value)
            .map((request) => request.key)
            .join(","),
    );

    function setPosition(id: number, position: StepPosition) {
        const step = steps.value[id];
        if (!step) {
            return;
        }
        // new objects: the original position objects are shared with the cached workflow
        step.position = { ...position };
        stepStore.updateStepValue(id, "position", { ...position });
    }

    function restore() {
        for (const [id, position] of originalPositions) {
            setPosition(id, position);
        }
        embedded.value = [];
        maxDisplacement.value = 0;
    }

    async function apply() {
        for (const step of Object.values(steps.value)) {
            if (!originalPositions.has(step.id) && step.position) {
                originalPositions.set(step.id, { ...step.position });
            }
        }
        // let shrunk nodes render, then measure them
        await nextTick();
        await new Promise((resolve) => requestAnimationFrame(resolve));

        const nodes: LayoutNode[] = [];
        for (const [id, position] of originalPositions) {
            const measured = stateStore.stepPosition[id];
            nodes.push({
                id,
                x: position.left,
                y: position.top,
                width: measured?.width ?? 150,
                height: measured?.height ?? 60,
            });
        }
        const requests = collectRequests(steps.value);
        const result = layoutEmbeddedOutputs(nodes, requests, collectEdges(steps.value), {
            direction: direction.value,
        });
        for (const [id, rect] of Object.entries(result.nodes)) {
            setPosition(Number(id), { left: rect.x, top: rect.y });
        }
        embedded.value = requests.map((request) => ({
            key: request.key,
            label: request.label,
            sourceId: request.sourceId,
            item: request.item,
            rect: result.embedded[request.key]!,
        }));
        maxDisplacement.value = result.maxDisplacement;
    }

    watch(
        [enabled, requestKeys, direction],
        async () => {
            if (enabled.value) {
                await apply();
            } else if (originalPositions.size) {
                restore();
            }
        },
        { immediate: true },
    );

    return { embedded, maxDisplacement };
}
