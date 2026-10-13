import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, expect, it, onTestFinished, vi } from "vitest";
import { ref } from "vue";

import type { WorkflowInvocationElementView } from "@/api/invocations";
import { ensureDefined } from "@/utils/assertions";

import WorkflowInvocationSteps from "./WorkflowInvocationSteps.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";

vi.mock("@/composables/useWorkflowInstance", () => ({
    useWorkflowInstance: () => ({
        workflow: ref({ id: "workflow_id", version: 0, steps: {} }),
        loading: ref(false),
        error: ref(null),
    }),
}));

vi.mock("@/composables/useInvocationGraph", () => ({
    useInvocationGraph: () => ({
        steps: ref({}),
        loading: ref(false),
        loadInvocationGraph: vi.fn().mockRejectedValue(new Error("429 Too Many Requests")),
    }),
}));

const localVue = getLocalVue();
enableAutoUnmount(afterEach);

it("shows an error when the invocation graph fails to load", async () => {
    const pinia = createTestingPinia({ createSpy: vi.fn });
    onTestFinished(() => {
        disposePinia(pinia);
        if (getActivePinia() === pinia) {
            setActivePinia(undefined);
        }
    });
    const invocation: Pick<WorkflowInvocationElementView, "id" | "workflow_id" | "steps"> = {
        id: "invocation_id",
        workflow_id: "workflow_id",
        steps: [],
    };
    const wrapper = shallowMount(WorkflowInvocationSteps, {
        props: {
            // This failed-load scenario supplies only identity and empty steps, omitting unused metadata.
            invocation: invocation as WorkflowInvocationElementView,
            stepsJobsSummary: [],
        },
        global: withPlugins(localVue, pinia),
    });
    await flushPromises();

    const errorAlert = ensureDefined(
        wrapper.findAllComponents(GAlert).find((alert) => alert.props("variant") === "danger"),
    );
    expect(errorAlert.text()).toContain("429 Too Many Requests");
});
