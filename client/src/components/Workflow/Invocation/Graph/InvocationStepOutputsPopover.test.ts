import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { GraphStep } from "@/composables/useInvocationGraph";

import InvocationOutputPreview from "./InvocationOutputPreview.vue";
import InvocationStepOutputsPopover from "./InvocationStepOutputsPopover.vue";
import GPopover from "@/components/BaseComponents/GPopover.vue";

const { server, http } = useServerMock();

const dataOutput = (name: string) => ({ name, extensions: ["input"], optional: false });

/** A scheduled tool step with two outputs; the invocation lists only `out_file1`, its workflow output */
const STEP = {
    id: 3,
    type: "tool",
    state: "ok",
    jobs: {},
    position: { left: 0, top: 0 },
    inputs: [],
    outputs: [dataOutput("out_file1"), dataOutput("out_file2")],
    workflow_outputs: [{ output_name: "out_file1", label: "summary" }],
    invocationStepId: "is3",
    outputItems: { out_file1: { src: "hda", id: "d1" } },
} as unknown as GraphStep;

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

/** Mount the popover and open it, as hovering its target does */
async function openPopover(step: GraphStep, stubs: Record<string, boolean> = {}) {
    const wrapper = shallowMount(InvocationStepOutputsPopover, {
        propsData: { step, target: () => undefined },
        localVue: getLocalVue(),
        stubs,
    });
    const popover = wrapper.findComponent(GPopover);
    if (popover.exists()) {
        popover.vm.$emit("update:show", true);
        await flushPromises();
    }
    return wrapper;
}

/** Close the popover and open it again, as moving off its target and back does */
async function hoverAgain(wrapper: Awaited<ReturnType<typeof openPopover>>) {
    const popover = wrapper.findComponent(GPopover);
    popover.vm.$emit("update:show", false);
    await flushPromises();
    popover.vm.$emit("update:show", true);
    await flushPromises();
}

function previewedOutputs(wrapper: Awaited<ReturnType<typeof openPopover>>) {
    return wrapper.findAll(".invocation-step-output").map((output) => ({
        label: output.find("[data-description='invocation step output label']").text(),
        item: output.findComponent(InvocationOutputPreview).props("item"),
    }));
}

beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
});

describe("InvocationStepOutputsPopover", () => {
    it("previews every output the invocation lists without fetching the step", async () => {
        const requests = serveStepDetails({});
        const step = {
            ...STEP,
            outputItems: { ...STEP.outputItems, out_file2: { src: "hdca", id: "c2" } },
        } as GraphStep;
        const wrapper = await openPopover(step);
        expect(previewedOutputs(wrapper)).toEqual([
            { label: "summary", item: { src: "hda", id: "d1" } },
            { label: "out_file2", item: { src: "hdca", id: "c2" } },
        ]);
        expect(requests.count).toBe(0);
    });

    it("says so when the step has produced nothing yet", async () => {
        serveStepDetails({});
        const wrapper = await openPopover({ ...STEP, outputItems: {} } as GraphStep);
        expect(previewedOutputs(wrapper)).toEqual([]);
        expect(wrapper.text()).toContain("No outputs produced yet.");
    });

    it("fetches the step's details again on the next hover once the step's state changed", async () => {
        const requests = serveStepDetails({});
        const wrapper = await openPopover({ ...STEP, state: "running" } as GraphStep);
        expect(requests.count).toBe(1);

        await hoverAgain(wrapper);
        expect(requests.count).toBe(1);

        serveStepDetails({ outputs: { out_file2: { id: "d2", src: "hda" } } });
        await wrapper.setProps({ step: STEP });
        await hoverAgain(wrapper);
        expect(previewedOutputs(wrapper).map((output) => output.label)).toEqual(["summary", "out_file2"]);
    });

    it("fetches the step's details again when the step's state changes while it's shown", async () => {
        serveStepDetails({});
        const wrapper = await openPopover({ ...STEP, state: "running" } as GraphStep);
        expect(previewedOutputs(wrapper).map((output) => output.label)).toEqual(["summary"]);

        serveStepDetails({ outputs: { out_file2: { id: "d2", src: "hda" } } });
        await wrapper.setProps({ step: STEP });
        await flushPromises();
        expect(previewedOutputs(wrapper).map((output) => output.label)).toEqual(["summary", "out_file2"]);
    });

    it("keeps its previews between hovers until the step's state changes", async () => {
        const requests = { count: 0 };
        server.use(
            http.get("/api/dataset_collections/{hdca_id}", ({ params, response }) => {
                requests.count++;
                return response.untyped(HttpResponse.json({ id: params.hdca_id, name: "lines", elements: [] }));
            }),
        );
        const step = {
            ...STEP,
            outputs: [dataOutput("out_file1")],
            outputItems: { out_file1: { src: "hdca", id: "c1" } },
        } as GraphStep;
        const wrapper = await openPopover(step, { InvocationOutputPreview: false, CollectionDisplay: false });
        expect(requests.count).toBe(1);

        await hoverAgain(wrapper);
        expect(requests.count).toBe(1);

        // a state change while hidden reloads nothing until the next hover
        const popover = wrapper.findComponent(GPopover);
        popover.vm.$emit("update:show", false);
        await wrapper.setProps({ step: { ...step, state: "error" } as GraphStep });
        await flushPromises();
        expect(requests.count).toBe(1);

        popover.vm.$emit("update:show", true);
        await flushPromises();
        expect(requests.count).toBe(2);
    });

    it.each([
        ["a step that isn't scheduled yet", { invocationStepId: undefined }],
        ["a parameter input, whose value its node shows", { type: "parameter_input" }],
    ])("has no previews for %s", async (_name, stepFields) => {
        const wrapper = await openPopover({ ...STEP, ...stepFields } as GraphStep);
        expect(wrapper.findComponent(GPopover).exists()).toBe(false);
    });
});
