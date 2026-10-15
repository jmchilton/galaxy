import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, expect, it, vi } from "vitest";
import { ref } from "vue";

import WorkflowInvocationSteps from "./WorkflowInvocationSteps.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import DelayedInput from "@/components/Common/DelayedInput.vue";
import WorkflowInvocationStep from "@/components/WorkflowInvocationState/WorkflowInvocationStep.vue";

const mocks = vi.hoisted(() => ({ workflow: {} as any, selection: undefined as any, load: vi.fn() }));
vi.mock("@/composables/invocationSelection", () => ({ useInvocationSelection: () => mocks.selection }));
vi.mock("@/composables/useWorkflowInstance", () => ({
    useWorkflowInstance: () => ({
        workflow: ref(mocks.workflow),
        loading: ref(false),
        error: ref(null),
    }),
}));

vi.mock("@/composables/useInvocationGraph", () => ({
    useInvocationGraph: () => ({
        steps: ref({}),
        loading: ref(false),
        loadInvocationGraph: mocks.load,
    }),
}));

const localVue = getLocalVue();
beforeEach(() => {
    mocks.workflow = { id: "workflow_id", version: 0, steps: {} };
    mocks.selection = undefined;
    mocks.load.mockReset().mockRejectedValue(new Error("429 Too Many Requests"));
});

it("shows an error when the invocation graph fails to load", async () => {
    const wrapper = shallowMount(WorkflowInvocationSteps as object, {
        propsData: {
            invocation: { id: "invocation_id", workflow_id: "workflow_id", steps: [] },
            stepsJobsSummary: [],
        },
        localVue,
        pinia: createTestingPinia({ createSpy: vi.fn }),
    });
    await flushPromises();

    const alert = wrapper.findAllComponents(GAlert).filter((w) => w.props("variant") === "danger");
    expect(alert.at(0)!.text()).toContain("429 Too Many Requests");
});

it("expands the grouped input and scrolls to it when a selection clears a previous search", async () => {
    mocks.workflow.steps = {
        0: { id: 0, type: "data_input", label: "reads" },
        1: { id: 1, type: "data_input", label: "reference" },
        2: { id: 2, type: "tool", label: "align" },
    };
    mocks.load.mockResolvedValue(undefined);
    mocks.selection = { stepIndex: ref<number | null>(null), stepTab: ref(), job: ref(), output: ref() };
    const scroll = vi.fn();
    Object.defineProperty(Element.prototype, "scrollIntoView", { configurable: true, value: scroll });
    const wrapper = shallowMount(WorkflowInvocationSteps as object, {
        propsData: {
            invocation: { id: "invocation_id", workflow_id: "workflow_id", steps: [] },
            stepsJobsSummary: [],
        },
        localVue,
        pinia: createTestingPinia({ createSpy: vi.fn }),
    });
    await flushPromises();
    wrapper.findComponent(DelayedInput).vm.$emit("change", "Step 3");
    await flushPromises();
    expect(wrapper.findAllComponents(WorkflowInvocationStep)).toHaveLength(1);
    mocks.selection.stepIndex.value = 0;
    await flushPromises();
    const inputs = wrapper.findAllComponents(WorkflowInvocationStep);
    expect(inputs).toHaveLength(3);
    expect(inputs.find((card) => card.props("workflowStep").id === 0)?.props("expanded")).toBe(true);
    expect(scroll).toHaveBeenCalled();
    wrapper.unmount();
});
