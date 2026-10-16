import { describe, expect, it } from "vitest";

import { getReplacements, rerunInputValue, WorkflowRunModel } from "./model";
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

describe("rerunInputValue", () => {
    const requestInputs = { labeled: "a", 1: { src: "hda", id: "d1" }, 2: [null], 3: 0 };

    it("reads labeled steps by label and unlabeled steps by step index", () => {
        expect(rerunInputValue(requestInputs, { step_label: "labeled", step_index: 0 }, 0)).toBe("a");
        expect(rerunInputValue(requestInputs, { step_label: null, step_index: 3 }, 3)).toBe(0);
        expect(rerunInputValue(requestInputs, { step_label: null, step_index: 5 }, 5)).toBeUndefined();
        // an unlabeled entry exported under "" is matched by position
        expect(rerunInputValue({ "": "b" }, { step_label: null, step_index: 7 }, 0)).toBe("b");
    });

    it("wraps data values and drops empty optional data inputs", () => {
        const dataStep = { step_label: null, step_index: 1, step_type: "data_input" };
        expect(rerunInputValue(requestInputs, dataStep, 1)).toEqual({ values: [{ src: "hda", id: "d1" }] });
        const emptyOptional = { step_label: null, step_index: 2, step_type: "data_input" };
        expect(rerunInputValue(requestInputs, emptyOptional, 2)).toBeUndefined();
    });
});
