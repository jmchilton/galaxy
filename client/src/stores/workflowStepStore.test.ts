import { createPinia, setActivePinia } from "pinia";

import { useWorkflowGraphStore } from "@/stores/workflowGraphStore";
import { type NewStep, type StepInputConnection, useWorkflowStepStore } from "@/stores/workflowStepStore";

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
        const graphStore = useWorkflowGraphStore("mock-workflow");
        const connectionStore = useConnectionStore("mock-workflow");
        graphStore.addStep(workflowStepZero);
        graphStore.addStep(workflowStepOne);
        expect(connectionStore.connections.length).toBe(1);
    });
    it("removes connection if step has connection", () => {
        const graphStore = useWorkflowGraphStore("mock-workflow");
        const connectionStore = useConnectionStore("mock-workflow");
        graphStore.addStep(workflowStepZero);
        const stepOne = graphStore.addStep(workflowStepOne);
        expect(connectionStore.connections.length).toBe(1);
        graphStore.removeStep(stepOne.id);
        expect(connectionStore.connections.length).toBe(0);
    });
});
