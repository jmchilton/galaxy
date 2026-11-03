import { describe, expect, it } from "vitest";

import { stepParameterErrors, stepParameterSubmissionErrors } from "./stepParameterErrors";
import { buildStepParameterTree, type ToolInput } from "./stepParameterTree";

function echoInputs(): ToolInput[] {
    return [
        { name: "threshold", type: "float", label: "Threshold", value: "0.5" },
        {
            name: "advanced",
            type: "section",
            title: "Advanced",
            inputs: [{ name: "label", type: "text", value: "run" }],
        },
        {
            name: "queries",
            type: "repeat",
            title: "Query",
            cache: [
                [{ name: "column_name", type: "text", value: "c1" }],
                [{ name: "column_name", type: "text", value: "c2" }],
            ],
        },
        {
            name: "cond",
            type: "conditional",
            test_param: { name: "filter_type", type: "select", label: "Filter type", value: "min", options: [] },
            cases: [{ value: "min", inputs: [{ name: "min", type: "integer", value: "1" }] }],
        },
    ];
}

const tree = buildStepParameterTree({
    steps: [
        { step_index: 0, step_type: "data_input", inputs: [] },
        { step_index: 1, step_type: "tool", step_name: "echo", inputs: echoInputs() },
        {
            step_index: 2,
            step_type: "subworkflow",
            step_name: "nested",
            subworkflow_steps: [{ step_index: 1, step_type: "tool", step_name: "echo", inputs: echoInputs() }],
        },
    ],
});

describe("stepParameterErrors", () => {
    it("reads runtime state errors keyed by step index and flat parameter name", () => {
        const errors = stepParameterErrors(tree, {
            1: {
                threshold: "not a number",
                "advanced|label": "lowercase",
                "queries_1|column_name": "bad",
                "cond|min": "x",
            },
        });
        expect(errors).toEqual([
            { key: "1/threshold", label: "Step 2: echo › Threshold", message: "not a number" },
            { key: "1/advanced/label", label: "Step 2: echo › Advanced › label", message: "lowercase" },
            { key: "1/queries/1/column_name", label: "Step 2: echo › Query 2 › column_name", message: "bad" },
            { key: "1/cond/min", label: "Step 2: echo › Filter type › min", message: "x" },
        ]);
    });

    it("reads inner steps' errors nested under their subworkflow steps", () => {
        const errors = stepParameterErrors(tree, { 2: { 1: { "queries_0|column_name": "bad" } } });
        expect(errors).toEqual([
            {
                key: "2/1/queries/0/column_name",
                label: "nested › Step 2: echo › Query 1 › column_name",
                message: "bad",
            },
        ]);
    });

    it("reads override validation errors keyed by path", () => {
        expect(stepParameterErrors(tree, { "2/1/thresold": "unknown parameter" })).toEqual([
            { key: "2/1/thresold", label: "nested › Step 2: echo › thresold", message: "unknown parameter" },
        ]);
        expect(stepParameterErrors(tree, { 7: "no step with this index" })).toEqual([
            { key: "7", label: "Step 8", message: "no step with this index" },
        ]);
    });

    it("keeps flat names the tree doesn't have, such as a conditional's test parameter", () => {
        const errors = stepParameterErrors(tree, { 1: { "cond|filter_type": "bad", "nope_3|x": "bad" } });
        expect(errors.map((error) => error.key)).toEqual(["1/cond/filter_type", "1/nope_3/x"]);
    });

    it("ignores err_data that isn't keyed by step", () => {
        expect(stepParameterErrors(tree, undefined)).toEqual([]);
        expect(stepParameterErrors(tree, {})).toEqual([]);
        expect(stepParameterErrors(tree, { missing_tool_ids: ["cat1"] })).toEqual([]);
        expect(stepParameterErrors(tree, "error")).toEqual([]);
    });
});

describe("stepParameterSubmissionErrors", () => {
    const errMsg = "Error computing workflow step runtime state";

    it("puts errors on the cards shown for them", () => {
        const errData = { 2: { 1: { threshold: "not a number", "advanced|label": "lowercase" } } };
        expect(stepParameterSubmissionErrors(tree, ["2/1/threshold", "2/1/advanced/label"], errData, errMsg)).toEqual({
            cards: { "2/1/threshold": "not a number", "2/1/advanced/label": "lowercase" },
            message: "Some step parameters are not valid. Fix the step parameters marked below.",
        });
    });

    it("lists the errors no card shows in the message, by label", () => {
        const errData = { 1: { threshold: "not a number", "cond|filter_type": "bad case" } };
        expect(stepParameterSubmissionErrors(tree, ["1/threshold"], errData, errMsg)).toEqual({
            cards: { "1/threshold": "not a number" },
            message: `${errMsg}: Step 2: echo › Filter type › filter_type - bad case. Fix the step parameters marked below.`,
        });
        expect(stepParameterSubmissionErrors(tree, [], errData, errMsg)).toEqual({
            cards: {},
            message: `${errMsg}: Step 2: echo › Threshold - not a number; Step 2: echo › Filter type › filter_type - bad case`,
        });
    });

    it("keeps the server's message for other errors", () => {
        expect(stepParameterSubmissionErrors(tree, ["1/threshold"], undefined, "Workflow not found")).toEqual({
            cards: {},
            message: "Workflow not found",
        });
    });
});
