import { createTestingPinia } from "@pinia/testing";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EffectScope, effectScope, ref } from "vue";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { GraphStep } from "@/composables/useInvocationGraph";

import { usePreferredOutputItems } from "./usePreferredOutputItems";

const { server, http } = useServerMock();

const dataOutput = (name: string) => ({ name, extensions: ["input"], optional: false });

/** A scheduled tool step naming its table as its preferred output; the invocation lists only its workflow output */
function toolStep(extra: Partial<GraphStep> = {}): GraphStep {
    return {
        id: 3,
        type: "tool",
        state: "ok",
        jobs: {},
        position: { left: 0, top: 0 },
        inputs: [],
        outputs: [dataOutput("table"), dataOutput("log")],
        workflow_outputs: [{ output_name: "log", label: "log" }],
        invocationStepId: "is3",
        outputItems: { log: { src: "hda", id: "d2" } },
        preferred_output: "table",
        ...extra,
    } as unknown as GraphStep;
}

/** Serve the step's details, counting the requests */
function serveStepDetails(stepDetails: object) {
    const requests = { count: 0 };
    server.use(
        http.get("/api/invocations/steps/{step_id}", ({ response }) => {
            requests.count++;
            return response.untyped(
                HttpResponse.json({ id: "is3", outputs: {}, output_collections: {}, ...stepDetails }),
            );
        }),
    );
    return requests;
}

let scope: EffectScope | undefined;

function setup(step: GraphStep, { enabled = true, detailedStepId = null as number | null } = {}) {
    const steps = ref<Record<string, GraphStep>>({ [step.id]: step });
    const enabledRef = ref(enabled);
    const detailed = ref(detailedStepId);
    scope = effectScope();
    const { items } = scope.run(() => usePreferredOutputItems(steps, enabledRef, () => detailed.value))!;
    return { items, steps };
}

beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
});

afterEach(() => {
    scope?.stop();
});

describe("usePreferredOutputItems", () => {
    it("shows a step as an output the invocation lists without fetching the step", async () => {
        const requests = serveStepDetails({});
        const { items } = setup(toolStep({ preferred_output: "log" }));
        await flushPromises();
        expect(items.value).toEqual({ 3: { src: "hda", id: "d2" } });
        expect(requests.count).toBe(0);
    });

    it("fetches the step's details for an output the invocation doesn't list", async () => {
        const requests = serveStepDetails({ output_collections: { table: { id: "c1", src: "hdca" } } });
        const { items } = setup(toolStep());
        await flushPromises();
        expect(items.value).toEqual({ 3: { src: "hdca", id: "c1" } });
        expect(requests.count).toBe(1);
    });

    it("keeps a step's item while it names the same output, so the step doesn't re-render", async () => {
        serveStepDetails({ outputs: { table: { id: "d1", src: "hda" } } });
        const { items, steps } = setup(toolStep());
        await flushPromises();
        const item = items.value[3];
        expect(item).toMatchObject({ src: "hda", id: "d1" });

        // the invocation listing another output reevaluates every step's item
        steps.value[3]!.outputItems = { log: { src: "hda", id: "d2" } };
        await flushPromises();
        expect(items.value[3]).toBe(item);
    });

    it("fetches the step's details again when its state changes, only while the output is still missing", async () => {
        let requests = serveStepDetails({});
        const { items, steps } = setup(toolStep({ state: "running" }));
        await flushPromises();
        expect(items.value).toEqual({});
        expect(requests.count).toBe(1);

        requests = serveStepDetails({ outputs: { table: { id: "d1", src: "hda" } } });
        steps.value[3]!.state = "ok";
        await flushPromises();
        expect(items.value).toEqual({ 3: { src: "hda", id: "d1" } });
        expect(requests.count).toBe(1);

        steps.value[3]!.state = "error";
        await flushPromises();
        expect(requests.count).toBe(1);
    });

    it.each([
        ["while disabled", {}, { enabled: false }],
        ["for a step that isn't a tool step", { type: "subworkflow" }, {}],
        ["for a name that isn't one of the step's outputs", { preferred_output: "gone" }, {}],
        ["for a step that names none", { preferred_output: null }, {}],
        ["for the step drawn with its connections", {}, { detailedStepId: 3 }],
    ])("shows no step %s, and fetches nothing", async (_name, stepFields, options) => {
        const requests = serveStepDetails({
            outputs: { table: { id: "d1", src: "hda" }, gone: { id: "d3", src: "hda" } },
        });
        const { items } = setup(toolStep({ preferred_output: "log", ...stepFields } as Partial<GraphStep>), options);
        await flushPromises();
        expect(items.value).toEqual({});
        expect(requests.count).toBe(0);
    });
});
