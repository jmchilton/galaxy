import { createTestingPinia } from "@pinia/testing";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EffectScope, effectScope, nextTick, ref } from "vue";

import type * as EmbeddedOutputLayout from "@/components/Workflow/Invocation/Graph/embeddedOutputLayout";
import {
    EMBEDDED_LAYOUT_GAP as GAP,
    layoutEmbeddedOutputs,
} from "@/components/Workflow/Invocation/Graph/embeddedOutputLayout";
import type { GraphStep } from "@/composables/useInvocationGraph";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { useWorkflowStepStore } from "@/stores/workflowStepStore";

import { EMBEDDED_OUTPUT_HEIGHT, EMBEDDED_OUTPUT_WIDTH, useEmbeddedOutputs } from "./useEmbeddedOutputs";

vi.mock("@/components/Workflow/Invocation/Graph/embeddedOutputLayout", async (importOriginal) => {
    const actual = await importOriginal<typeof EmbeddedOutputLayout>();
    return { ...actual, layoutEmbeddedOutputs: vi.fn(actual.layoutEmbeddedOutputs) };
});

const STORE_ID = "invocation-inv1";
const STEP_WIDTH = 144;
const STEP_HEIGHT = 55;

function graphStep(id: number, left: number, top: number, extra: Partial<GraphStep> = {}): GraphStep {
    return {
        id,
        type: "tool",
        state: "ok",
        jobs: {},
        position: { left, top },
        inputs: [],
        outputs: [],
        input_connections: {},
        workflow_outputs: [],
        ...extra,
    } as unknown as GraphStep;
}

/**
 * A table step with two workflow outputs, one unlabeled; a collection step; an unscheduled step; a step fed by the
 * table step, in its card's row; and a step fed by that one, outside every card's rows
 */
function buildSteps(): Record<string, GraphStep> {
    return {
        0: graphStep(0, 0, 0, {
            workflow_outputs: [
                { output_name: "table", label: "summary" },
                { output_name: "log", label: null },
            ],
            outputItems: { table: { src: "hda", id: "d1" }, log: { src: "hda", id: "d2" } },
        } as Partial<GraphStep>),
        1: graphStep(1, 0, 400, {
            workflow_outputs: [{ output_name: "list", label: "lines" }],
            outputItems: { list: { src: "hdca", id: "c1" } },
        } as Partial<GraphStep>),
        2: graphStep(2, 0, 800, {
            workflow_outputs: [{ output_name: "out", label: "not yet" }],
        } as Partial<GraphStep>),
        3: graphStep(3, 260, 0, {
            input_connections: { input: [{ id: 0, output_name: "table" }] },
        } as Partial<GraphStep>),
        4: graphStep(4, 520, 300, {
            input_connections: { input: { id: 3, output_name: "out_file1" } },
        } as Partial<GraphStep>),
    };
}

let scope: EffectScope | undefined;

function setup(steps: Record<string, GraphStep>) {
    const stepStore = useWorkflowStepStore(STORE_ID);
    const stateStore = useWorkflowStateStore(STORE_ID);
    for (const step of Object.values(steps)) {
        stepStore.addStep({ ...step }, false, false);
        stateStore.stepPosition[step.id] = { width: STEP_WIDTH, height: STEP_HEIGHT } as never;
    }
    const stepsRef = ref(steps);
    const enabled = ref(false);
    scope = effectScope();
    const { embedded, hasEmbeddableOutputs } = scope.run(() => useEmbeddedOutputs(STORE_ID, stepsRef, enabled))!;
    return { steps: stepsRef, enabled, embedded, hasEmbeddableOutputs, stepStore, stateStore };
}

/** Let the layout run: it waits for the next animation frame */
async function settle() {
    await nextTick();
    await new Promise((resolve) => requestAnimationFrame(resolve));
    await flushPromises();
}

beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
});

afterEach(() => {
    scope?.stop();
});

describe("useEmbeddedOutputs", () => {
    it("embeds nothing and moves nothing until enabled", async () => {
        const { embedded, steps, hasEmbeddableOutputs } = setup(buildSteps());
        await settle();
        expect(embedded.value).toEqual([]);
        expect(steps.value[3]!.position).toEqual({ left: 260, top: 0 });
        expect(hasEmbeddableOutputs.value).toBe(true);
    });

    it("has nothing to embed before any labeled workflow output is produced", () => {
        const steps = buildSteps();
        delete steps[0]!.outputItems;
        delete steps[1]!.outputItems;
        const { hasEmbeddableOutputs } = setup(steps);
        expect(hasEmbeddableOutputs.value).toBe(false);
    });

    it("embeds labeled workflow outputs that have produced a dataset or collection", async () => {
        const { embedded, enabled } = setup(buildSteps());
        enabled.value = true;
        await settle();

        expect(embedded.value.map(({ label, step, item }) => ({ label, sourceId: step.id, item }))).toEqual([
            { label: "summary", sourceId: 0, item: { src: "hda", id: "d1" } },
            { label: "lines", sourceId: 1, item: { src: "hdca", id: "c1" } },
        ]);
        const [summary, lines] = embedded.value;
        expect(summary!.rect).toEqual({
            x: STEP_WIDTH + GAP,
            y: 0,
            width: EMBEDDED_OUTPUT_WIDTH,
            height: EMBEDDED_OUTPUT_HEIGHT,
        });
        // the step as laid out, for the connector
        expect(summary!.stepRect).toEqual({ x: 0, y: 0, width: STEP_WIDTH, height: STEP_HEIGHT });
        // collections render as a short element list
        expect(lines!.rect.height).toBeLessThan(EMBEDDED_OUTPUT_HEIGHT);
    });

    it("pushes steps in the way to the right on the graph and in the step store, carrying their downstream steps", async () => {
        const { enabled, steps, stepStore } = setup(buildSteps());
        enabled.value = true;
        await settle();

        const pushedTo = { left: STEP_WIDTH + GAP + EMBEDDED_OUTPUT_WIDTH + GAP, top: 0 };
        expect(steps.value[3]!.position).toEqual(pushedTo);
        expect(stepStore.getStep(3)!.position).toEqual(pushedTo);
        expect(steps.value[1]!.position).toEqual({ left: 0, top: 400 });
        // step 4 is clear of every card, but its connection from step 3 keeps its length
        expect(steps.value[4]!.position).toEqual({ left: pushedTo.left + (520 - 260), top: 300 });
    });

    it("restores the author's positions when disabled", async () => {
        const { enabled, embedded, steps, stepStore } = setup(buildSteps());
        enabled.value = true;
        await settle();
        enabled.value = false;
        await settle();

        expect(embedded.value).toEqual([]);
        expect(steps.value[3]!.position).toEqual({ left: 260, top: 0 });
        expect(stepStore.getStep(3)!.position).toEqual({ left: 260, top: 0 });
    });

    it("lays out again from the author's positions when a step's measured size changes", async () => {
        const { enabled, steps, stateStore } = setup(buildSteps());
        // the first layout runs before the embedded view's narrower steps are measured
        stateStore.stepPosition[0] = { width: STEP_WIDTH + 100, height: STEP_HEIGHT } as never;
        enabled.value = true;
        await settle();
        expect(steps.value[3]!.position).toEqual({
            left: STEP_WIDTH + 100 + GAP + EMBEDDED_OUTPUT_WIDTH + GAP,
            top: 0,
        });

        // once the source is measured narrower, the step it pushed moves back
        stateStore.stepPosition[0] = { width: STEP_WIDTH, height: STEP_HEIGHT } as never;
        await settle();
        expect(steps.value[3]!.position).toEqual({ left: STEP_WIDTH + GAP + EMBEDDED_OUTPUT_WIDTH + GAP, top: 0 });
    });

    it("lays out once when every step is measured again in the same frame", async () => {
        const { enabled, steps, stateStore } = setup(buildSteps());
        enabled.value = true;
        await settle();
        vi.mocked(layoutEmbeddedOutputs).mockClear();

        // as when the embedded view shrinks the steps: each step's size arrives in its own resize callback
        for (const id of Object.keys(steps.value)) {
            stateStore.stepPosition[Number(id)] = { width: STEP_WIDTH - 10, height: STEP_HEIGHT } as never;
            await nextTick();
        }
        await settle();
        expect(layoutEmbeddedOutputs).toHaveBeenCalledTimes(1);
        expect(steps.value[3]!.position).toEqual({ left: STEP_WIDTH - 10 + GAP + EMBEDDED_OUTPUT_WIDTH + GAP, top: 0 });
    });

    it("doesn't read the steps' measured sizes while disabled", async () => {
        const { stateStore } = setup(buildSteps());
        await settle();
        // scrolling the page measures every step again
        let reads = 0;
        stateStore.stepPosition[0] = {
            get width() {
                reads++;
                return STEP_WIDTH;
            },
            height: STEP_HEIGHT,
        } as never;
        await settle();
        expect(reads).toBe(0);
    });

    it("embeds an output once its step produces it", async () => {
        const { enabled, embedded, steps } = setup(buildSteps());
        enabled.value = true;
        await settle();

        steps.value[2]!.outputItems = { out: { src: "hda", id: "d3" } };
        await settle();
        expect(embedded.value.map((output) => output.label)).toEqual(["summary", "lines", "not yet"]);
    });
});
