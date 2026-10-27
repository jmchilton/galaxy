import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { useWorkflowNodeInspectorStore } from "@/stores/workflowNodeInspectorStore";
import type { Step } from "@/stores/workflowStepStore";

import { simpleSteps } from "./test_fixtures";

import NodeInspector from "./NodeInspector.vue";

const step = Object.values(simpleSteps)[0] as Step;
const labelled = { ...step, label: "my step" };

function mountInspector(props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
    return mount(NodeInspector as object, {
        props: { step, datatypes: [], ...props },
        global: {
            ...localVue,
            plugins: [...(localVue.plugins ?? []), createTestingPinia({ createSpy: vi.fn })],
            stubs: { ...localVue.stubs, FormTool: true, FormDefault: true, IdleLoad: true, DraggableSeparator: true },
        },
    });
}

describe("NodeInspector", () => {
    it("stores the size when remember size is checked", async () => {
        const wrapper = mountInspector();
        const inspectorStore = useWorkflowNodeInspectorStore();

        await wrapper.find("input[type='checkbox']").setValue(true);

        expect(inspectorStore.setStored).toHaveBeenCalledWith(step, true);
    });

    it("links a labelled step of a saved workflow to its runs", () => {
        const link = mountInspector({ step: labelled, storedWorkflowId: "wf1" }).find(".node-inspector-compare-runs");
        expect(link.exists()).toBe(true);
        expect(link.attributes("href")).toBe("/comparisons?kind=step_runs&workflow_id=wf1&step_label=my+step");
    });

    it.each([
        ["the workflow has unsaved changes", { hasChanges: true }],
        ["the step is unlabelled", { step: { ...step, label: null } }],
        ["the workflow was never saved", { storedWorkflowId: undefined }],
    ])("offers no runs link when %s", (_description, change) => {
        const linked = { step: labelled, storedWorkflowId: "wf1" };
        expect(mountInspector(linked).find(".node-inspector-compare-runs").exists()).toBe(true);
        expect(
            mountInspector({ ...linked, ...change })
                .find(".node-inspector-compare-runs")
                .exists(),
        ).toBe(false);
    });
});
