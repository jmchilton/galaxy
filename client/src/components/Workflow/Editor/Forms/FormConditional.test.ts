import "@/composables/__mocks__/filter";

import { getLocalVue } from "@tests/vitest/helpers";
import { mount, shallowMount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useUndoRedoStore } from "@/stores/undoRedoStore";
import { useConnectionStore } from "@/stores/workflowConnectionStore";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { type Step, type Steps, useWorkflowStepStore } from "@/stores/workflowStepStore";

import { useStepActions } from "../Actions/stepActions";

import FormConditional from "./FormConditional.vue";
import FormElement from "@/components/Form/FormElement.vue";

const { confirmMock } = vi.hoisted(() => ({ confirmMock: vi.fn() }));

vi.mock("@/composables/confirmDialog", () => ({
    useConfirmDialog: () => ({ confirm: confirmMock }),
}));

const GATED_STEP_ID = 3;
const WORKFLOW_ID = "mock-workflow";

function makeSteps(gatedStepOverrides: Partial<Step> = {}): Steps {
    const dataInput = (id: number, optional: boolean) =>
        ({
            id,
            type: "data_input",
            name: "Input dataset",
            inputs: [],
            outputs: [{ name: "output", extensions: ["input"], optional }],
            input_connections: {},
            position: { left: 0, top: 0 },
            tool_state: {},
            workflow_outputs: [],
        }) as unknown as Step;

    return {
        1: dataInput(1, true),
        2: dataInput(2, false),
        3: {
            id: GATED_STEP_ID,
            type: "tool",
            name: "Concatenate datasets",
            inputs: [
                {
                    name: "input1",
                    label: "First input",
                    multiple: false,
                    extensions: ["txt"],
                    optional: false,
                    input_type: "dataset",
                },
                {
                    name: "cond|input2",
                    label: "Second input",
                    multiple: false,
                    extensions: ["txt"],
                    optional: false,
                    input_type: "dataset",
                },
                {
                    name: "queries_0|input3",
                    label: "Repeat input",
                    multiple: false,
                    extensions: ["txt"],
                    optional: false,
                    input_type: "dataset",
                },
                {
                    name: "input4",
                    label: "Always present input",
                    multiple: false,
                    extensions: ["txt"],
                    optional: false,
                    input_type: "dataset",
                },
            ],
            outputs: [{ name: "out_file1", extensions: ["txt"], optional: false }],
            input_connections: {
                input1: { id: 1, output_name: "output" },
                "cond|input2": { id: 1, output_name: "output" },
                "queries_0|input3": { id: 1, output_name: "output" },
                input4: { id: 2, output_name: "output" },
            },
            position: { left: 0, top: 0 },
            tool_state: {
                input1: '{"__class__": "ConnectedValue"}',
                cond: { input2: { __class__: "ConnectedValue" } },
                queries: '[{"__index__": 0, "input3": {"__class__": "ConnectedValue"}}]',
            },
            workflow_outputs: [],
            ...gatedStepOverrides,
        } as unknown as Step,
    } as unknown as Steps;
}

function mountConditional(
    gatedStepOverrides: Partial<Step> = {},
    onUpdateStep?: (id: number, partial: Partial<Step>) => void,
    mountFn: typeof shallowMount = shallowMount,
): VueWrapper {
    // getLocalVue() activates the pinia it installs, so the steps added here are the ones the form reads.
    const globalConfig = getLocalVue();
    const stepStore = useWorkflowStepStore(WORKFLOW_ID);
    const steps = makeSteps(gatedStepOverrides);
    Object.values(steps).forEach((step) => stepStore.addStep(step, false, Boolean(onUpdateStep)));

    return mountFn(FormConditional, {
        props: { step: steps[GATED_STEP_ID]!, ...(onUpdateStep && { onOnUpdateStep: onUpdateStep }) },
        global: { ...globalConfig, provide: { workflowId: WORKFLOW_ID } },
    });
}

/** Mounts with live connections and applies each emitted update the way the editor does. */
function mountApplyingUpdates(gatedStepOverrides: Partial<Step>): VueWrapper {
    return mountConditional(gatedStepOverrides, (id, partial) =>
        useStepActions(
            useWorkflowStepStore(WORKFLOW_ID),
            useUndoRedoStore(WORKFLOW_ID),
            useWorkflowStateStore(WORKFLOW_ID),
            useConnectionStore(WORKFLOW_ID),
            WORKFLOW_ID,
        ).updateStep(id, partial),
    );
}

function gatedConnectionNames(): string[] {
    return useConnectionStore(WORKFLOW_ID)
        .connections.filter((connection) => connection.input.stepId === GATED_STEP_ID)
        .map((connection) => connection.input.name)
        .sort();
}

function gatedStep(): Step {
    return useWorkflowStepStore(WORKFLOW_ID).getStep(GATED_STEP_ID)!;
}

function formElement(wrapper: VueWrapper, id: string) {
    const element = wrapper.findAllComponents(FormElement).find((candidate) => candidate.props("id") === id);
    if (!element) {
        throw new Error(`No form element '${id}'`);
    }
    return element;
}

function modeElement(wrapper: VueWrapper) {
    return formElement(wrapper, "__conditional");
}

function gatedInputElement(wrapper: VueWrapper) {
    return formElement(wrapper, "__when_input");
}

/** `options` reaches FormElement through attrs rather than a declared prop. */
function optionValues(element: ReturnType<typeof formElement>): string[] {
    return (element.vm.$attrs["options"] as unknown as string[][]).map((option) => option[1]!);
}

function updates(wrapper: VueWrapper): Array<[number, Partial<Step>]> {
    return (wrapper.emitted().onUpdateStep ?? []) as Array<[number, Partial<Step>]>;
}

function lastUpdate(wrapper: VueWrapper): Partial<Step> {
    const emitted = updates(wrapper);
    return emitted[emitted.length - 1]![1];
}

describe("FormConditional", () => {
    beforeEach(() => {
        confirmMock.mockReset();
    });

    describe("mode round-trips", () => {
        it("reads an ungated step as unconditional", () => {
            const wrapper = mountConditional();
            expect(modeElement(wrapper).props("value")).toBe("none");
        });

        it("reads the boolean gate", () => {
            const wrapper = mountConditional({ when: "$(inputs.when)" });
            expect(modeElement(wrapper).props("value")).toBe("boolean");
        });

        it("reads a generated presence gate and the input it addresses", () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            expect(modeElement(wrapper).props("value")).toBe("presence");
            expect(gatedInputElement(wrapper).props("value")).toBe("input1");
        });

        it("reads a nested presence gate", () => {
            const wrapper = mountConditional({
                when: "$(inputs.cond.input2 !== null)",
            });
            expect(modeElement(wrapper).props("value")).toBe("presence");
            expect(gatedInputElement(wrapper).props("value")).toBe("cond|input2");
        });

        it("reads a repeat presence gate", () => {
            const wrapper = mountConditional({ when: "$(inputs.queries[0].input3 !== null)" });
            expect(modeElement(wrapper).props("value")).toBe("presence");
            expect(gatedInputElement(wrapper).props("value")).toBe("queries_0|input3");
        });

        it("reads anything else as a custom expression", () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 != null)" });
            expect(modeElement(wrapper).props("value")).toBe("custom");
        });
    });

    describe("gateable inputs", () => {
        it("offers every connection whose source can be absent, nested ones included", () => {
            const wrapper = mountConditional();
            expect(optionValues(modeElement(wrapper))).toContain("presence");

            const gated = mountConditional({ when: "$(inputs.input1 !== null)" });
            expect(optionValues(gatedInputElement(gated))).toEqual(["input1", "cond|input2", "queries_0|input3"]);
        });

        it("does not offer the presence mode when nothing gateable is connected", () => {
            const wrapper = mountConditional({
                input_connections: { input4: { id: 2, output_name: "output" } },
            });
            expect(optionValues(modeElement(wrapper))).not.toContain("presence");
        });
    });

    describe("writing a gate", () => {
        it("writes the boolean gate and clears its connection", () => {
            const wrapper = mountConditional();
            modeElement(wrapper).vm.$emit("input", "boolean");
            expect(lastUpdate(wrapper).when).toBe("$(inputs.when)");
            expect(lastUpdate(wrapper).input_connections).toHaveProperty("when", undefined);
        });

        it("rewrites the expression when the gated input changes", () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            gatedInputElement(wrapper).vm.$emit("input", "cond|input2");
            expect(lastUpdate(wrapper).when).toBe("$(inputs.cond.input2 !== null)");
            expect(lastUpdate(wrapper)).not.toHaveProperty("input_connections");
        });

        it("writes an indexed presence gate for a repeat input", () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            gatedInputElement(wrapper).vm.$emit("input", "queries_0|input3");
            expect(lastUpdate(wrapper).when).toBe("$(inputs.queries[0].input3 !== null)");
        });

        it("ignores a selection of the mode already in effect", () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            modeElement(wrapper).vm.$emit("input", "presence");
            expect(updates(wrapper)).toHaveLength(0);
            modeElement(wrapper).vm.$emit("input", "boolean");
            expect(updates(wrapper)).toHaveLength(1);
        });
    });

    describe("clearing a gate", () => {
        it("clears a generated gate without asking", async () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            modeElement(wrapper).vm.$emit("input", "none");
            await flushPromises();
            expect(confirmMock).not.toHaveBeenCalled();
            expect(lastUpdate(wrapper).when).toBeUndefined();
        });

        it("asks before clearing a hand-written expression", async () => {
            confirmMock.mockResolvedValue(true);
            const wrapper = mountConditional({ when: "$(inputs.input1 != null)" });
            modeElement(wrapper).vm.$emit("input", "none");
            await flushPromises();
            expect(confirmMock).toHaveBeenCalled();
            expect(lastUpdate(wrapper).when).toBeUndefined();
        });

        it("keeps a hand-written expression when the user declines", async () => {
            confirmMock.mockResolvedValue(false);
            const wrapper = mountConditional({ when: "$(inputs.input1 != null)" });
            modeElement(wrapper).vm.$emit("input", "none");
            await flushPromises();
            expect(confirmMock).toHaveBeenCalled();
            expect(updates(wrapper)).toHaveLength(0);
        });

        it("asks before replacing a hand-written expression with the boolean gate", async () => {
            confirmMock.mockResolvedValue(false);
            const wrapper = mountConditional({ when: "$(inputs.flag && inputs.other !== null)" });
            modeElement(wrapper).vm.$emit("input", "boolean");
            await flushPromises();
            expect(confirmMock).toHaveBeenCalled();
            expect(updates(wrapper)).toHaveLength(0);
        });

        it("asks before replacing a hand-written expression with a presence gate", async () => {
            confirmMock.mockResolvedValue(false);
            const wrapper = mountConditional({ when: "$(inputs.flag && inputs.other !== null)" });
            modeElement(wrapper).vm.$emit("input", "presence");
            await flushPromises();
            expect(confirmMock).toHaveBeenCalled();
            expect(updates(wrapper)).toHaveLength(0);
        });

        it("replaces a hand-written expression once the user agrees", async () => {
            confirmMock.mockResolvedValue(true);
            const wrapper = mountConditional({ when: "$(inputs.flag && inputs.other !== null)" });
            modeElement(wrapper).vm.$emit("input", "boolean");
            await flushPromises();
            expect(lastUpdate(wrapper).when).toBe("$(inputs.when)");
        });

        it("does not ask when the expression is one this form generated", async () => {
            const wrapper = mountConditional({ when: "$(inputs.input1 !== null)" });
            modeElement(wrapper).vm.$emit("input", "boolean");
            await flushPromises();
            expect(confirmMock).not.toHaveBeenCalled();
            expect(lastUpdate(wrapper).when).toBe("$(inputs.when)");
        });

        it("renders a hand-written expression as read-only text without rewriting it", async () => {
            const expression = "$(inputs.input1 != null && inputs.other)";
            const wrapper = mountConditional({ when: expression }, undefined, mount);
            await flushPromises();
            const customElement = formElement(wrapper, "__when");
            expect(customElement.props("value")).toBe(expression);
            expect(customElement.props("disabled")).toBe(true);
            const custom = wrapper.find("#form-element-__when");
            expect(custom.find(".ui-form-preview").text()).toBe(expression);
            expect(custom.find("input").exists()).toBe(false);
            expect(updates(wrapper)).toHaveLength(0);
        });
    });

    describe("dropping connections the new condition leaves without a port", () => {
        const toolConnections = makeSteps()[GATED_STEP_ID]!.input_connections;
        const probeSource = { id: 1, output_name: "output" };
        const twinProbe = {
            when: "$(inputs.probe !== null)",
            input_connections: { ...toolConnections, probe: probeSource },
        };

        it.each([["presence"], ["none"]])(
            "drops the boolean gate's connection when switching to %s",
            async (newMode) => {
                const wrapper = mountApplyingUpdates({
                    when: "$(inputs.when)",
                    input_connections: { ...toolConnections, when: { id: 2, output_name: "output" } },
                });
                modeElement(wrapper).vm.$emit("input", newMode);
                await flushPromises();
                expect(gatedConnectionNames()).toEqual(Object.keys(toolConnections).sort());
                expect(Object.keys(gatedStep().input_connections).sort()).toEqual(Object.keys(toolConnections).sort());
            },
        );

        it.each([
            ["none", (wrapper: VueWrapper) => modeElement(wrapper).vm.$emit("input", "none"), []],
            ["boolean", (wrapper: VueWrapper) => modeElement(wrapper).vm.$emit("input", "boolean"), ["when"]],
            ["another input", (wrapper: VueWrapper) => gatedInputElement(wrapper).vm.$emit("input", "input1"), []],
        ])("drops a twin's probe link when its presence gate moves to %s", async (_target, change, newPorts) => {
            const wrapper = mountApplyingUpdates(twinProbe);
            expect(gatedInputElement(wrapper).props("value")).toBe("probe");

            change(wrapper);
            await flushPromises();
            expect(gatedConnectionNames()).toEqual(Object.keys(toolConnections).sort());
            // The boolean gate adds its own, still unconnected, `when` port.
            const expectedKeys = [...Object.keys(toolConnections), ...newPorts].sort();
            expect(Object.keys(gatedStep().input_connections).sort()).toEqual(expectedKeys);
        });

        it("drops the links a replaced hand-written expression read", async () => {
            confirmMock.mockResolvedValue(true);
            const wrapper = mountApplyingUpdates({
                when: "$(inputs.flag && inputs.input1 !== null)",
                input_connections: { ...toolConnections, flag: { id: 2, output_name: "output" } },
            });
            modeElement(wrapper).vm.$emit("input", "presence");
            await flushPromises();
            expect(gatedStep().when).toBe("$(inputs.input1 !== null)");
            expect(gatedConnectionNames()).toEqual(Object.keys(toolConnections).sort());
        });

        it("restores the condition and the dropped link with a single undo", async () => {
            const wrapper = mountApplyingUpdates(twinProbe);
            modeElement(wrapper).vm.$emit("input", "none");
            await flushPromises();
            expect(gatedConnectionNames()).not.toContain("probe");

            useUndoRedoStore(WORKFLOW_ID).undo();
            expect(gatedStep().when).toBe(twinProbe.when);
            expect(gatedStep().input_connections).toHaveProperty("probe", [probeSource]);
            expect(gatedConnectionNames()).toContain("probe");
        });
    });
});
