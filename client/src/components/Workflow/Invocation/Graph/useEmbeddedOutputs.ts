import { computed, onScopeDispose, type Ref, ref, watch } from "vue";

import {
    type EmbeddedNodeRequest,
    type LayoutEdge,
    layoutEmbeddedOutputs,
    type LayoutNode,
} from "@/components/Workflow/Invocation/Graph/embeddedOutputLayout";
import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useWorkflowStores } from "@/composables/workflowStores";
import type { Rectangle } from "@/utils/geometry";

export const EMBEDDED_OUTPUT_WIDTH = 260;
export const EMBEDDED_OUTPUT_HEIGHT = 170;
/** Collections render as a short element list */
const EMBEDDED_COLLECTION_HEIGHT = 120;

/** A step's size until it is first measured */
const UNMEASURED_STEP = { width: 150, height: 60 };

export interface EmbeddedOutput {
    key: string;
    label: string;
    item: InvocationOutputItem;
    /** The step producing the output, whose state its preview follows */
    step: GraphStep;
    /** Where the output is drawn */
    rect: Rectangle;
    /** Where its step is laid out, to connect the two */
    stepRect: Rectangle;
}

type StepPosition = NonNullable<GraphStep["position"]>;

/** Workflow outputs that have produced a dataset/collection, keyed for the layout */
function collectRequests(steps: Record<string, GraphStep>) {
    const requests: (EmbeddedNodeRequest & { label: string; item: InvocationOutputItem; step: GraphStep })[] = [];
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
                step,
                width: EMBEDDED_OUTPUT_WIDTH,
                height: item.src === "hdca" ? EMBEDDED_COLLECTION_HEIGHT : EMBEDDED_OUTPUT_HEIGHT,
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
export function useEmbeddedOutputs(storeId: string, steps: Ref<Record<string, GraphStep>>, enabled: Ref<boolean>) {
    const { stateStore, stepStore } = useWorkflowStores(storeId);

    const originalPositions = new Map<number, StepPosition>();
    const embedded = ref<EmbeddedOutput[]>([]);

    const requestKeys = computed(() =>
        collectRequests(steps.value)
            .map((request) => request.key)
            .join(","),
    );
    /** Whether any workflow output has produced something to embed yet */
    const hasEmbeddableOutputs = computed(() => requestKeys.value !== "");

    function setPosition(id: number, position: StepPosition) {
        const step = steps.value[id];
        if (!step || (step.position?.left === position.left && step.position?.top === position.top)) {
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
        originalPositions.clear();
        embedded.value = [];
    }

    function recordOriginalPositions() {
        for (const step of Object.values(steps.value)) {
            if (!originalPositions.has(step.id) && step.position) {
                originalPositions.set(step.id, { ...step.position });
            }
        }
    }

    function apply() {
        const nodes: LayoutNode[] = [];
        for (const [id, position] of originalPositions) {
            const { width, height } = stateStore.stepPosition[id] ?? UNMEASURED_STEP;
            nodes.push({ id, x: position.left, y: position.top, width, height });
        }
        const requests = collectRequests(steps.value);
        const result = layoutEmbeddedOutputs(nodes, requests, collectEdges(steps.value));
        for (const [id, rect] of Object.entries(result.nodes)) {
            setPosition(Number(id), { left: rect.x, top: rect.y });
        }
        embedded.value = requests.map((request) => ({
            key: request.key,
            label: request.label,
            item: request.item,
            step: request.step,
            rect: result.embedded[request.key]!,
            stepRect: result.nodes[request.sourceId]!,
        }));
    }

    let queuedFrame: number | undefined;

    /** Lay out at most once per frame. Each step reports its own size as the steps resize, so a layout per change
     * would lay out the whole graph again for every step. */
    function queueApply() {
        queuedFrame ??= requestAnimationFrame(() => {
            queuedFrame = undefined;
            if (enabled.value) {
                apply();
            }
        });
    }
    onScopeDispose(() => {
        if (queuedFrame !== undefined) {
            cancelAnimationFrame(queuedFrame);
        }
    });

    /** Measured step sizes (not positions), so the layout reruns after shrinking or content loading. Scrolling the
     * page updates every step's measured position, so read them only while embedding. */
    const stepSizes = computed(() =>
        enabled.value
            ? Object.entries(stateStore.stepPosition)
                  .map(([id, rect]) => `${id}:${Math.round(rect.width)}x${Math.round(rect.height)}`)
                  .join(",")
            : "",
    );

    watch(
        [enabled, requestKeys, stepSizes],
        () => {
            if (enabled.value) {
                recordOriginalPositions();
                // sizes may still be pre-shrink here; `stepSizes` reruns the layout once they settle
                queueApply();
            } else if (originalPositions.size) {
                restore();
            }
        },
        { immediate: true },
    );

    return { embedded, hasEmbeddableOutputs };
}
