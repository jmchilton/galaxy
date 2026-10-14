import { describe, expect, it } from "vitest";

import { getReplacements, rerunHasStepParameters, rerunInputValue, WorkflowRunModel } from "./model";
import sampleRunData1 from "./testdata/run1.json";

describe("test basic parameter replacement", () => {
    it("should replace", async () => {
        const step_1 = {
            inputs: [
                { name: "input_1", value: "${wp_1}", wp_linked: true },
                { name: "input_2", value: "input_2", step_linked: [{ index: 0, step_type: "data" }] },
            ],
        };
        const stepData = [{ input: { values: ["input_new_data"] } }];
        const wpData = { wp_1: "input_new_wp" };
        const result = getReplacements(step_1.inputs, stepData, wpData);
        expect(result.input_1).toEqual("input_new_wp");
        expect(result.input_2.values[0]).toEqual("input_new_data");
    });
});

describe("WorkflowRunModel status", () => {
    it("expands tool steps with disconnected data inputs", async () => {
        const runModel = new WorkflowRunModel(sampleRunData1);
        expect(runModel.hasOpenToolSteps).toBe(true);
    });
    it("collapses tool steps with optional disconnected data inputs", async () => {
        const optionalDataSteps = {
            ...sampleRunData1,
            steps: [
                {
                    id: "cat",
                    inputs: [
                        {
                            label: "Concatenate Dataset",
                            model_class: "DataToolParameter",
                            multiple: false,
                            name: "input1",
                            optional: true,
                            options: {
                                hda: [],
                                hdca: [],
                            },
                            text_value: "Not available.",
                            type: "data",
                            value: {
                                __class__: "RuntimeValue",
                            },
                        },
                    ],
                    model_class: "Tool",
                    name: "Concatenate datasets (for test workflows)",
                    replacement_parameters: [],
                    step_index: 0,
                    step_label: "",
                    step_name: "Concatenate datasets (for test workflows)",
                    step_type: "tool",
                    step_version: "1.0.0",
                },
            ],
        };
        const runModel = new WorkflowRunModel(optionalDataSteps);
        expect(runModel.hasOpenToolSteps).toBe(false);
    });
});

describe("rerun helpers", () => {
    it("reads rerun values for labeled and unlabeled input steps", () => {
        const requestInputs = { labeled: "a", 1: { src: "hda", id: "d1" }, 2: [null] };
        expect(rerunInputValue(requestInputs, { step_label: "labeled", step_index: 0 }, 0)).toBe("a");
        const dataStep = { step_label: null, step_index: 1, step_type: "data_input" };
        expect(rerunInputValue(requestInputs, dataStep, 1)).toEqual({ values: [{ src: "hda", id: "d1" }] });
        const emptyOptional = { step_label: null, step_index: 2, step_type: "data_input" };
        expect(rerunInputValue(requestInputs, emptyOptional, 2)).toBeUndefined();
    });

    it("detects requests carrying tool step parameters", () => {
        expect(rerunHasStepParameters(undefined)).toBe(false);
        expect(rerunHasStepParameters({ inputs: { 0: "a" }, parameters: null })).toBe(false);
        expect(rerunHasStepParameters({ parameters: {}, replacement_params: { name: "x" } })).toBe(false);
        expect(rerunHasStepParameters({ parameters: { 1: { num_lines: 2 } } })).toBe(true);
    });
});
