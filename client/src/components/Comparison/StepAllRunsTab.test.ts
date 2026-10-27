import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";

import { useWorkflowStore } from "@/stores/workflowStore";

import StepAllRunsTab from "./StepAllRunsTab.vue";
import GTab from "@/components/BaseComponents/GTab.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";

const RUNS_STUB = {
    name: "StepRunsTab",
    props: {
        workflowId: String,
        instance: Boolean,
        storedWorkflowId: String,
        stepLabel: String,
        currentInvocationId: String,
    },
    template: "<div />",
};

function mountInTabs(props: { graphLabel?: string | null; invocationLabel?: string | null }) {
    const invocation = {
        id: "inv-1",
        workflow_id: "wf-instance",
        steps: [{ id: "s0" }, { id: "s1", workflow_step_label: props.invocationLabel }],
    };
    const Host = defineComponent({
        render: () =>
            h(GTabs as object, null, {
                default: () => [
                    h(GTab as object, { title: "Jobs" }, { default: () => "jobs" }),
                    h(StepAllRunsTab as object, {
                        invocation,
                        workflowStep: { id: 1 },
                        graphStep: props.graphLabel === undefined ? undefined : { label: props.graphLabel },
                    }),
                ],
            }),
    });
    const localVue = getLocalVue();
    useWorkflowStore().workflowsByInstanceId = { "wf-instance": { id: "stored-wf" } } as never;
    return mount(Host, { global: { ...localVue, stubs: { ...localVue.stubs, StepRunsTab: RUNS_STUB } } });
}

describe("StepAllRunsTab", () => {
    it("is disabled with an explanation for an unlabelled step", async () => {
        const wrapper = mountInTabs({ graphLabel: null, invocationLabel: null });
        await wrapper.vm.$nextTick();
        const link = wrapper.find(".invocation-step-all-runs-tab .nav-link");
        expect(link.text()).toBe("Label this step to compare its runs");
        expect(link.attributes("aria-disabled")).toBe("true");
        await link.trigger("click");
        expect(wrapper.findComponent(RUNS_STUB).exists()).toBe(false);
    });

    it("loads runs only once opened, by the graph step's label", async () => {
        const wrapper = mountInTabs({ graphLabel: "count_reads", invocationLabel: "stale" });
        await wrapper.vm.$nextTick();
        const link = wrapper.find(".invocation-step-all-runs-tab .nav-link");
        expect(link.text()).toBe("All runs");
        expect(wrapper.findComponent(RUNS_STUB).exists()).toBe(false);
        await link.trigger("click");
        const runs = wrapper.findComponent(RUNS_STUB);
        expect(runs.props()).toEqual({
            workflowId: "wf-instance",
            instance: true,
            storedWorkflowId: "stored-wf",
            stepLabel: "count_reads",
            currentInvocationId: "inv-1",
        });
    });

    it("falls back to the invocation step's label outside the graph", async () => {
        const wrapper = mountInTabs({ invocationLabel: "count_reads" });
        await wrapper.vm.$nextTick();
        await wrapper.find(".invocation-step-all-runs-tab .nav-link").trigger("click");
        expect(wrapper.findComponent(RUNS_STUB).props("stepLabel")).toBe("count_reads");
    });
});
