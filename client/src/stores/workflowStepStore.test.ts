import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createTestStep } from "@/components/Workflow/Editor/test_fixtures";
import {
    getCombinedStepInputs,
    type InputTerminalSource,
    type NewStep,
    type StepInputConnection,
    useWorkflowStepStore,
} from "@/stores/workflowStepStore";

import { useConnectionStore } from "./workflowConnectionStore";

const stepInputConnection: StepInputConnection = {
    "1": {
        output_name: "output",
        id: 0,
    },
};

const workflowStepZero: NewStep = {
    id: 0,
    input_connections: {},
    inputs: [],
    name: "a step",
    outputs: [],
    post_job_actions: {},
    tool_state: {},
    type: "tool",
    workflow_outputs: [],
};

const workflowStepOne: NewStep = { ...workflowStepZero, input_connections: stepInputConnection };

describe("Connection Store", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it("adds step", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        expect(stepStore.steps).toStrictEqual({});
        stepStore.addStep(workflowStepZero);
        expect(stepStore.getStep(0)).toStrictEqual(workflowStepZero);
        expect(workflowStepZero.id).toBe(0);
    });
    it("removes step", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        const addedStep = stepStore.addStep(workflowStepZero);
        expect(addedStep.id).toBe(0);
        stepStore.removeStep(addedStep.id);
        expect(stepStore.getStep(0)).toBe(undefined);
    });
    it("creates connection if step has connection", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        const connectionStore = useConnectionStore("mock-workflow");
        stepStore.addStep(workflowStepZero);
        stepStore.addStep(workflowStepOne);
        expect(connectionStore.connections.length).toBe(1);
    });
    it("removes connection if step has connection", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        const connectionStore = useConnectionStore("mock-workflow");
        stepStore.addStep(workflowStepZero);
        const stepOne = stepStore.addStep(workflowStepOne);
        expect(connectionStore.connections.length).toBe(1);
        stepStore.removeStep(stepOne.id);
        expect(connectionStore.connections.length).toBe(0);
    });
});

describe("getCombinedStepInputs", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    const regularInput: InputTerminalSource = {
        name: "input_dataset",
        label: "Input Dataset",
        multiple: false,
        optional: false,
        extensions: ["txt"],
        input_type: "dataset",
    };

    const stepWithRegularInputs = createTestStep(0, {
        inputs: [regularInput],
        outputs: [],
    });

    const stepWithWhen = createTestStep(1, {
        inputs: [regularInput],
        outputs: [],
        when: "$(inputs.check_value)",
        inputConnections: {
            check_value: { output_name: "output", id: 0 },
        },
    });

    it("returns only regular inputs when step has no extra inputs", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        const step = stepStore.addStep(stepWithRegularInputs);

        const combinedInputs = getCombinedStepInputs(step, stepStore);

        expect(combinedInputs).toHaveLength(1);
        expect(combinedInputs[0]?.name).toBe("input_dataset");
    });

    it("includes extra inputs when step has conditional parameters", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        stepStore.addStep(workflowStepZero); // Add step 0 as output source
        const step = stepStore.addStep(stepWithWhen);

        const combinedInputs = getCombinedStepInputs(step, stepStore);

        expect(combinedInputs.length).toBeGreaterThan(1);
        const inputNames = combinedInputs.map((i) => i.name);
        expect(inputNames).toContain("check_value");
        expect(inputNames).toContain("input_dataset");
    });

    it("places extra inputs before regular inputs", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        stepStore.addStep(workflowStepZero);
        const step = stepStore.addStep(stepWithWhen);

        const combinedInputs = getCombinedStepInputs(step, stepStore);

        // Extra inputs should come first
        expect(combinedInputs[0]?.name).toBe("check_value");
        expect(combinedInputs[1]?.name).toBe("input_dataset");
    });

    function extraInputNames(when: string, connectionName: string) {
        const stepStore = useWorkflowStepStore("mock-workflow");
        stepStore.addStep(workflowStepZero);
        const step = stepStore.addStep(
            createTestStep(1, {
                when,
                inputConnections: { [connectionName]: { output_name: "output", id: 0 } },
            }),
        );
        return getCombinedStepInputs(step, stepStore).map((input) => input.name);
    }

    it.each([
        { when: "$(inputs.flag)", connection: "flag" },
        { when: '$(inputs["flag"])', connection: "flag" },
        { when: "$(inputs['flag'])", connection: "flag" },
        { when: "$(inputs?.flag)", connection: "flag" },
        { when: '$(inputs?.["flag"])', connection: "flag" },
        { when: "$(!inputs.flag)", connection: "flag" },
        { when: "${inputs.when}", connection: "when" },
        { when: '$(inputs["my-flag"])', connection: "my-flag" },
        { when: "$(inputs.cond.flag)", connection: "cond|flag" },
        { when: '$(inputs["cond"]["flag"])', connection: "cond|flag" },
        { when: "$(inputs.cond?.flag)", connection: "cond|flag" },
        { when: '$(inputs["cond|flag"])', connection: "cond|flag" },
    ])("shows a terminal for connection $connection read by $when", ({ when, connection }) => {
        expect(extraInputNames(when, connection)).toEqual([connection]);
    });

    it.each([
        { when: "$(inputs.flag_2)", connection: "flag", reason: "a longer name" },
        { when: "$(inputs.check_value)", connection: "check", reason: "a longer name" },
        { when: "$(inputs.other_flag)", connection: "flag", reason: "a name with the same suffix" },
        { when: "$(other.inputs.flag)", connection: "flag", reason: "a property of another object" },
        { when: "$(inputs.cond.flag2)", connection: "cond|flag", reason: "a longer nested name" },
        { when: "$(inputs.flag.cond)", connection: "cond|flag", reason: "the segments reversed" },
    ])("shows no terminal for connection $connection when $when reads $reason", ({ when, connection }) => {
        expect(extraInputNames(when, connection)).toEqual([]);
    });

    it("handles step with no inputs gracefully", () => {
        const stepStore = useWorkflowStepStore("mock-workflow");
        const step = stepStore.addStep(workflowStepZero); // Step with empty inputs

        const combinedInputs = getCombinedStepInputs(step, stepStore);

        expect(combinedInputs).toHaveLength(0);
    });
});
