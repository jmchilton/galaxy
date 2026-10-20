import { computed, nextTick, type Ref, ref, watch } from "vue";

import {
    type EmbeddedNodeRequest,
    type LayoutEdge,
    layoutEmbeddedOutputs,
    type LayoutNode,
    type LayoutRect,
    type NudgeDirection,
} from "@/components/Workflow/Editor/modules/embeddedOutputLayout";
import { type GraphStep, type InvocationOutputItem, preferredOutputItem } from "@/composables/useInvocationGraph";
import { useWorkflowStores } from "@/composables/workflowStores";

export const EMBEDDED_OUTPUT_WIDTH = 360;
export const EMBEDDED_OUTPUT_HEIGHT = 260;
/** Rough size of a shrunk step; a step shown as its preferred output grew from this */
const SHRUNK_STEP_SIZE = { width: 144, height: 60 };

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
            // the step itself already stands in for its preferred output
            if (!workflowOutput.label || !item || workflowOutput.output_name === step.preferred_output) {
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
        [
            ...collectRequests(steps.value).map((request) => request.key),
            ...Object.values(steps.value)
                .filter((step) => preferredOutputItem(step))
                .map((step) => `preferred-${step.id}`),
        ].join(","),
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
        // sizes may still be pre-shrink here; `stepSizes` reruns the layout once they settle
        await nextTick();

        const nodes: LayoutNode[] = [];
        for (const [id, position] of originalPositions) {
            const measured = stateStore.stepPosition[id];
            const step = steps.value[id];
            const grown = step && preferredOutputItem(step);
            nodes.push({
                id,
                x: position.left,
                y: position.top,
                width: measured?.width ?? SHRUNK_STEP_SIZE.width,
                height: measured?.height ?? SHRUNK_STEP_SIZE.height,
                ...(grown ? { baseWidth: SHRUNK_STEP_SIZE.width, baseHeight: SHRUNK_STEP_SIZE.height } : {}),
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

    /** Measured step sizes (not positions), so the layout reruns after shrinking or content loading */
    const stepSizes = computed(() =>
        Object.entries(stateStore.stepPosition)
            .map(([id, rect]) => `${id}:${Math.round(rect.width)}x${Math.round(rect.height)}`)
            .join(","),
    );

    watch(
        [enabled, requestKeys, direction, stepSizes],
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
