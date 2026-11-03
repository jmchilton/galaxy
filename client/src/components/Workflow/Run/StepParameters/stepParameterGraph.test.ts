import { describe, expect, it } from "vitest";

import type { Step } from "@/stores/workflowStepStore";

import { stepParameterGraphSteps } from "./stepParameterGraph";
import { buildStepParameterTree } from "./stepParameterTree";

const tree = buildStepParameterTree({
    steps: [
        { step_index: 0, step_type: "data_input", inputs: [{ name: "input", type: "data" }] },
        {
            step_index: 1,
            step_type: "tool",
            step_name: "Echo",
            inputs: [
                { name: "threshold", type: "float", value: "0.5" },
                { name: "mode", type: "select", value: "fast", options: [["Fast", "fast", true]] },
                { name: "column", type: "data_column", is_dynamic: true, value: "1" },
            ],
        },
        {
            step_index: 2,
            step_type: "subworkflow",
            step_name: "Nested",
            subworkflow_steps: [
                { step_index: 1, step_type: "tool", inputs: [{ name: "flag", type: "boolean", value: false }] },
                {
                    step_index: 2,
                    step_type: "subworkflow",
                    subworkflow_steps: [
                        { step_index: 1, step_type: "tool", inputs: [{ name: "label", type: "text", value: "x" }] },
                    ],
                },
            ],
        },
        { step_index: 3, step_type: "pause" },
    ],
});

const graphSteps = Object.fromEntries(
    [
        { id: 0, type: "data_input" },
        { id: 1, type: "tool" },
        { id: 2, type: "subworkflow" },
        { id: 3, type: "pause" },
    ].map((step) => [String(step.id), step as Step]),
);

describe("stepParameterGraphSteps", () => {
    it("counts picked parameters per tool step and across all of a subworkflow's inner steps", () => {
        const steps = stepParameterGraphSteps(graphSteps, tree, new Set(["1/threshold", "2/2/1/label"]));
        expect(steps["0"]).toBe(graphSteps["0"]);
        expect(steps["1"]!.nodeText).toBe("<b>1</b> of 2 parameters chosen");
        expect(steps["1"]!.headerClass).toEqual({ "node-header-invocation": true, "header-ok": true });
        expect(steps["2"]!.nodeText).toBe("<b>1</b> of 2 parameters chosen");
        expect(steps["3"]!.nodeText).toBe("No parameters to choose");
        expect(steps["3"]!.headerClass).toBeUndefined();
    });

    it("says how many parameters a step offers when none are picked", () => {
        const steps = stepParameterGraphSteps(graphSteps, tree, new Set());
        expect(steps["1"]!.nodeText).toBe("2 parameters to choose from");
        expect(steps["1"]!.headerClass).toBeUndefined();
        expect(steps["1"]!.headerIcon).toBeUndefined();
    });
});
