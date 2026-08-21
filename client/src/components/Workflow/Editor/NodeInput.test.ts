import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { type Directive, type DirectiveBinding, nextTick, ref } from "vue";

import { testDatatypesMapper } from "@/components/Datatypes/test_fixtures";
import type { useWorkflowStores } from "@/composables/workflowStores";
import { useUndoRedoStore } from "@/stores/undoRedoStore";
import { useConnectionStore } from "@/stores/workflowConnectionStore";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { type Step, type Steps, useWorkflowStepStore } from "@/stores/workflowStepStore";

import { type OutputTerminals, terminalFactory } from "./modules/terminals";
import { advancedSteps, mockOffset } from "./test_fixtures";

import NodeInput from "./NodeInput.vue";

const { confirmMock } = vi.hoisted(() => ({ confirmMock: vi.fn() }));

vi.mock("@/composables/confirmDialog", () => ({
    useConfirmDialog: () => ({ confirm: confirmMock }),
}));

const workflowId = "node-input-drop-preview";
const transform = ref({ x: 0, y: 0, k: 1 });

class ResizeObserver {
    observe = vi.fn();
    unobserve = vi.fn();
    disconnect = vi.fn();
}

// eslint-disable-next-line compat/compat
window.ResizeObserver = ResizeObserver;

// The drop reason is the title of NodeInput's v-g-tooltip; record it where the test can read it.
function recordTooltipTitle(el: HTMLElement, binding: DirectiveBinding<{ title?: string }>) {
    el.setAttribute("data-tooltip-title", binding.value?.title ?? "");
}
const recordingTooltip: Directive<HTMLElement, { title?: string }> = {
    mounted: recordTooltipTitle,
    updated: recordTooltipTitle,
};

function stepForLabel(label: string, steps: Steps): Step {
    const step = Object.values(steps).find((step) => step.label === label);
    if (!step) {
        throw new Error(`No step labeled '${label}'`);
    }
    return step;
}

describe("NodeInput drop preview", () => {
    let globalConfig: ReturnType<typeof getLocalVue>;
    let steps: Steps;

    beforeEach(() => {
        // getLocalVue() activates the pinia it installs, so the stores filled here are the ones NodeInput reads.
        globalConfig = getLocalVue();
        const stepStore = useWorkflowStepStore(workflowId);
        steps = JSON.parse(JSON.stringify(advancedSteps)) as Steps;
        Object.values(steps).forEach((step) => stepStore.addStep(step));
    });

    function outputTerminal(stepLabel: string): OutputTerminals {
        const step = stepForLabel(stepLabel, steps);
        return terminalFactory(step.id, step.outputs[0]!, testDatatypesMapper, {
            connectionStore: useConnectionStore(workflowId),
            stepStore: useWorkflowStepStore(workflowId),
            undoRedoStore: useUndoRedoStore(workflowId),
        } as unknown as ReturnType<typeof useWorkflowStores>) as OutputTerminals;
    }

    function addReceiverStep(label: string, type: Step["type"]): void {
        const template = stepForLabel("simple data", steps);
        const id = Math.max(...Object.values(steps).map((step) => step.id)) + 1;
        const step = {
            ...JSON.parse(JSON.stringify(template)),
            id,
            type,
            label,
            name: label,
            input_connections: {},
        } as Step;
        steps[id] = step;
        useWorkflowStepStore(workflowId).addStep(step);
    }

    function mountInput(stepLabel: string): VueWrapper {
        const step = stepForLabel(stepLabel, steps);
        return shallowMount(NodeInput, {
            props: {
                input: step.inputs[0]!,
                stepId: step.id,
                datatypesMapper: testDatatypesMapper,
                stepPosition: step.position!,
                rootOffset: mockOffset,
                scale: 1,
                scroll: { x: ref(0), y: ref(0) },
                parentNode: undefined,
                readonly: false,
                blank: false,
            },
            global: {
                ...globalConfig,
                directives: { ...globalConfig.directives, "g-tooltip": recordingTooltip },
                provide: { transform, workflowId, isDragging: ref(true) },
            },
        });
    }

    function dropReason(wrapper: VueWrapper): string {
        return wrapper.find(".input-terminal").attributes("data-tooltip-title") ?? "";
    }

    async function preview(outputStepLabel: string, inputStepLabel: string) {
        useWorkflowStateStore(workflowId).draggingTerminal = outputTerminal(outputStepLabel);
        const wrapper = mountInput(inputStepLabel);
        await nextTick();
        return wrapper;
    }

    it("shows a directly accepted drop in green", async () => {
        const wrapper = await preview("data input", "simple data");

        expect(wrapper.find(".input-terminal").classes()).toContain("can-accept");
        expect(wrapper.find(".input-terminal").classes()).not.toContain("can-not-accept");
    });

    it("shows a presence-gated drop in green with an actionable explanation", async () => {
        const wrapper = await preview("optional data input", "simple data");

        expect(wrapper.find(".input-terminal").classes()).toContain("can-accept");
        expect(wrapper.find(".input-terminal").classes()).not.toContain("can-not-accept");
        expect(dropReason(wrapper)).toContain("Drop to connect and run this step only when From is provided.");
        expect(dropReason(wrapper)).not.toContain("Cannot connect an optional output");
    });

    it("offers presence gating for a required subworkflow input", async () => {
        addReceiverStep("required subworkflow", "subworkflow");

        const wrapper = await preview("optional data input", "required subworkflow");

        expect(wrapper.find(".input-terminal").classes()).toContain("can-accept");
        expect(wrapper.find(".input-terminal").classes()).not.toContain("can-not-accept");
        expect(dropReason(wrapper)).toContain("Drop to connect and run this step only when From is provided.");
    });

    it("does not offer presence gating for a pause step", async () => {
        addReceiverStep("pause for review", "pause");

        const wrapper = await preview("optional data input", "pause for review");

        expect(wrapper.find(".input-terminal").classes()).toContain("can-not-accept");
        expect(wrapper.find(".input-terminal").classes()).not.toContain("can-accept");
        expect(dropReason(wrapper)).toContain("Cannot connect an optional output to a non-optional input");
        expect(dropReason(wrapper)).not.toContain("run this step only when");
    });

    it("keeps a genuinely incompatible drop orange with its rejection", async () => {
        const wrapper = await preview("optional data input", "list collection input");

        expect(wrapper.find(".input-terminal").classes()).toContain("can-not-accept");
        expect(wrapper.find(".input-terminal").classes()).not.toContain("can-accept");
        expect(dropReason(wrapper)).toContain("Cannot attach a data output to a collection input.");
    });
});

describe("NodeInput drop onto a required input", () => {
    let globalConfig: ReturnType<typeof getLocalVue>;
    let steps: Steps;

    beforeEach(() => {
        confirmMock.mockReset();
        globalConfig = getLocalVue();
        const stepStore = useWorkflowStepStore(workflowId);
        steps = JSON.parse(JSON.stringify(advancedSteps)) as Steps;
        Object.values(steps).forEach((step) => stepStore.addStep(step));
    });

    async function dropOptionalOutputOnRequiredInput() {
        const source = stepForLabel("optional data input", steps);
        const target = stepForLabel("simple data", steps);
        const wrapper = shallowMount(NodeInput, {
            props: {
                input: target.inputs[0]!,
                stepId: target.id,
                datatypesMapper: testDatatypesMapper,
                stepPosition: target.position!,
                rootOffset: mockOffset,
                scale: 1,
                scroll: { x: ref(0), y: ref(0) },
                parentNode: undefined,
                readonly: false,
                blank: false,
            },
            global: { ...globalConfig, provide: { transform, workflowId, isDragging: ref(false) } },
        });
        const payload = JSON.stringify({ stepId: source.id, output: source.outputs[0] });
        await wrapper.find(".node-input").trigger("drop", { dataTransfer: { getData: () => payload } });
        await flushPromises();
        return { source, target };
    }

    function connectionsInto(stepId: number) {
        return useConnectionStore(workflowId).connections.filter((connection) => connection.input.stepId === stepId);
    }

    it("connects and gates the step as one undoable action once confirmed", async () => {
        confirmMock.mockResolvedValue(true);
        const { source, target } = await dropOptionalOutputOnRequiredInput();
        const stepStore = useWorkflowStepStore(workflowId);

        expect(confirmMock).toHaveBeenCalledOnce();
        expect(connectionsInto(target.id).map((connection) => connection.output.stepId)).toEqual([source.id]);
        expect(stepStore.getStep(target.id)?.when).toBe("$(inputs.input !== null)");

        useUndoRedoStore(workflowId).undo();

        expect(connectionsInto(target.id)).toHaveLength(0);
        expect(stepStore.getStep(target.id)?.when).toBeUndefined();
    });

    it("changes nothing when the user declines the gate", async () => {
        confirmMock.mockResolvedValue(false);
        const { target } = await dropOptionalOutputOnRequiredInput();

        expect(confirmMock).toHaveBeenCalledOnce();
        expect(connectionsInto(target.id)).toHaveLength(0);
        expect(useWorkflowStepStore(workflowId).getStep(target.id)?.when).toBeUndefined();
    });
});
