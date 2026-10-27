import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { useUndoRedoStore } from "@/stores/undoRedoStore";
import { useConnectionStore } from "@/stores/workflowConnectionStore";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { type Step, useWorkflowStepStore } from "@/stores/workflowStepStore";

import { useStepActions } from "../Actions/stepActions";

import FormConditional from "./FormConditional.vue";
import FormElement from "@/components/Form/FormElement.vue";

const WORKFLOW_ID = "mock-workflow";

/** Mounts with live connections and applies each emitted update the way the editor does. */
function mountApplyingUpdates(step: Partial<Step>) {
    // getLocalVue() activates the pinia it installs, so it has to come before the stores.
    const globalConfig = getLocalVue();
    const stepStore = useWorkflowStepStore(WORKFLOW_ID);
    const { updateStep } = useStepActions(
        stepStore,
        useUndoRedoStore(WORKFLOW_ID),
        useWorkflowStateStore(WORKFLOW_ID),
        useConnectionStore(WORKFLOW_ID),
        WORKFLOW_ID,
    );
    const gated = stepStore.addStep({ inputs: [{ name: "input1" }], outputs: [], ...step } as Step);
    return shallowMount(FormConditional, {
        props: { step: gated, onOnUpdateStep: updateStep },
        global: globalConfig,
    });
}

describe("FormConditional", () => {
    it("drops the boolean gate's connection when the condition is cleared", () => {
        const input1 = { id: 1, output_name: "output" };
        const wrapper = mountApplyingUpdates({
            id: 3,
            when: "$(inputs.when)",
            input_connections: { input1, when: { id: 2, output_name: "output" } },
        });
        wrapper.findComponent(FormElement).vm.$emit("input", false);

        expect(wrapper.emitted("onUpdateStep")).toEqual([[3, { when: undefined }]]);
        expect(useWorkflowStepStore(WORKFLOW_ID).getStep(3)?.input_connections).toEqual({ input1: [input1] });
        const connected = useConnectionStore(WORKFLOW_ID).connections.map((connection) => connection.input.name);
        expect(connected).toEqual(["input1"]);
    });
});
