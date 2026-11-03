import { describe, expect, it } from "vitest";

import {
    buildStepParameterOverrides,
    buildStepParameterTree,
    displayValue,
    filterTree,
    parseStepParameterOverridesArg,
    resolveStepParameterKeys,
    stepParameterKeyLabel,
    stepParameterOverrideValues,
    treeLeaves,
    typedParameterValue,
} from "./stepParameterTree";

function echoStepInputs() {
    return [
        { name: "input1", type: "hidden", connected: true },
        { name: "threshold", type: "float", label: "Threshold", value: "0.5", help: "Minimum score." },
        { name: "column", type: "data_column", data_ref: "input1", label: "Column", value: "1" },
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
            test_param: {
                name: "filter_type",
                type: "select",
                label: "Filter type",
                value: "min",
                options: [
                    ["Minimum", "min", true],
                    ["Regular expression", "regex", false],
                ],
            },
            cases: [
                { value: "min", inputs: [{ name: "min", type: "integer", value: "1" }] },
                { value: "regex", inputs: [{ name: "pattern", type: "text", value: ".*" }] },
            ],
        },
    ];
}

const model = {
    steps: [
        { step_index: 0, step_type: "data_input", inputs: [{ name: "input", type: "data" }] },
        { step_index: 1, step_type: "tool", step_name: "Echo", inputs: echoStepInputs() },
        {
            step_index: 2,
            step_type: "subworkflow",
            step_name: "QC",
            inputs: [],
            subworkflow_steps: [
                {
                    step_index: 1,
                    step_type: "tool",
                    step_name: "Inner echo",
                    inputs: [
                        { name: "input1", type: "data", value: { __class__: "ConnectedValue" } },
                        { name: "lines", type: "integer", value: { __class__: "ConnectedValue" } },
                        { name: "threshold", type: "float", label: "Threshold", value: "0.25" },
                    ],
                },
                {
                    step_index: 2,
                    step_type: "subworkflow",
                    step_name: "Deeper",
                    subworkflow_steps: [
                        {
                            step_index: 0,
                            step_type: "tool",
                            step_name: "Deepest",
                            inputs: [{ name: "mode", type: "text", value: "x" }],
                        },
                    ],
                },
            ],
        },
    ],
};

describe("buildStepParameterTree", () => {
    it("lists the leaves of tool steps and of tool steps inside subworkflows, keyed by path", () => {
        const keys = treeLeaves(buildStepParameterTree(model)).map((leaf) => [leaf.id, leaf.disabledReason]);
        expect(keys).toEqual([
            ["1/threshold", undefined],
            ["1/column", "Options depend on a data input"],
            ["1/advanced/label", undefined],
            ["1/queries/0/column_name", undefined],
            ["1/queries/1/column_name", undefined],
            ["1/cond/min", undefined],
            ["2/1/threshold", undefined],
            ["2/2/0/mode", undefined],
        ]);
    });

    it("gives each leaf its step path and its path in the step's tool state", () => {
        const leaves = treeLeaves(buildStepParameterTree(model));
        const byKey = Object.fromEntries(leaves.map((leaf) => [leaf.id, [leaf.stepPath, leaf.paramPath]]));
        expect(byKey["1/queries/1/column_name"]).toEqual([[1], ["queries", 1, "column_name"]]);
        expect(byKey["2/2/0/mode"]).toEqual([[2, 2, 0], ["mode"]]);
    });

    it("labels steps inside subworkflows with the subworkflows they are in", () => {
        const [, qc] = buildStepParameterTree(model);
        expect(qc!.label).toBe("Step 3: QC");
        expect(qc!.children.map((node) => node.label)).toEqual(["QC › Step 2: Inner echo", "QC › Step 3: Deeper"]);
        expect(qc!.children[1]!.children[0]!.label).toBe("QC › Deeper › Step 1: Deepest");
        const deepest = treeLeaves([qc!]).find((leaf) => leaf.id === "2/2/0/mode")!;
        expect(deepest.path).toEqual(["QC › Deeper › Step 1: Deepest", "mode"]);
    });

    it("filters by label and keeps ancestors", () => {
        const filtered = treeLeaves(filterTree(buildStepParameterTree(model), "query"));
        expect(filtered.map((leaf) => leaf.id)).toEqual(["1/queries/0/column_name", "1/queries/1/column_name"]);
        expect(treeLeaves(filterTree(buildStepParameterTree(model), "deeper")).map((leaf) => leaf.id)).toEqual([
            "2/2/0/mode",
        ]);
    });
});

describe("displayValue", () => {
    it("formats scalars, option labels, lists and empty values", () => {
        expect(displayValue({ value: 0.5 })).toBe("0.5");
        expect(displayValue({ value: false })).toBe("false");
        expect(displayValue({ value: "" })).toBeUndefined();
        expect(displayValue({ value: null })).toBeUndefined();
        const options = [
            ["Alpha", "a", false],
            ["Beta", "b", false],
        ];
        expect(displayValue({ value: ["a", "b"], options })).toBe("Alpha, Beta");
        expect(displayValue({ value: "zzz", options })).toBe("zzz");
    });
});

describe("resolveStepParameterKeys", () => {
    it("keeps workflow order and drops unknown and disabled keys", () => {
        const tree = buildStepParameterTree(model);
        const { leaves, dropped } = resolveStepParameterKeys(tree, [
            "2/1/threshold",
            "1/cond/min",
            "1/threshold",
            "1/cond/pattern",
            "1/column",
        ]);
        expect(leaves.map((leaf) => leaf.id)).toEqual(["1/threshold", "1/cond/min", "2/1/threshold"]);
        expect(dropped.map((d) => [d.key, d.label])).toEqual([
            ["1/cond/pattern", "Step 2: Echo › Filter type › pattern"],
            ["1/column", "Step 2: Echo › Column"],
        ]);
    });

    it("labels keys the workflow doesn't have as far as the tree reaches, counting steps from 1", () => {
        const tree = buildStepParameterTree(model);
        expect(stepParameterKeyLabel(tree, "1/queries/1/column_name")).toBe("Step 2: Echo › Query 2 › column_name");
        expect(stepParameterKeyLabel(tree, "1/queries/5/column_name")).toBe("Step 2: Echo › Query 6 › column_name");
        expect(stepParameterKeyLabel(tree, "2/2/0/nope")).toBe("QC › Deeper › Step 1: Deepest › nope");
        expect(stepParameterKeyLabel(tree, "2/7/x")).toBe("Step 3: QC › Step 8 › x");
        expect(stepParameterKeyLabel(tree, "9/x")).toBe("Step 10 › x");
    });
});

describe("step_parameter_overrides", () => {
    it("nests values by step path and tool state path, padding repeats with empty instances", () => {
        expect(
            buildStepParameterOverrides([
                { stepPath: [1], paramPath: ["threshold"], value: 0.9 },
                { stepPath: [1], paramPath: ["queries", 1, "column_name"], value: "c9" },
                { stepPath: [1], paramPath: ["cond", "min"], value: 5 },
                { stepPath: [2, 2, 0], paramPath: ["mode"], value: "y" },
            ]),
        ).toEqual({
            1: { threshold: 0.9, queries: [{}, { column_name: "c9" }], cond: { min: 5 } },
            2: { 2: { 0: { mode: "y" } } },
        });
    });

    it("reads leaf values back by key, leaving out empty repeat instances", () => {
        const values = stepParameterOverrideValues({
            1: { threshold: 0.9, queries: [{}, { column_name: "c9" }], cond: { min: null }, multi: ["a", "b"] },
            2: { 1: { threshold: 0.1 } },
        });
        expect(Object.fromEntries(values)).toEqual({
            "1/threshold": 0.9,
            "1/queries/1/column_name": "c9",
            "1/cond/min": null,
            "1/multi": ["a", "b"],
            "2/1/threshold": 0.1,
        });
        expect(stepParameterOverrideValues(null).size).toBe(0);
    });

    it("round trips through the tree's leaves", () => {
        const leaves = treeLeaves(buildStepParameterTree(model)).filter((leaf) => !leaf.disabledReason);
        const overrides = buildStepParameterOverrides(
            leaves.map((leaf) => ({ stepPath: leaf.stepPath, paramPath: leaf.paramPath, value: leaf.id })),
        );
        const values = stepParameterOverrideValues(overrides);
        expect([...values.keys()]).toEqual(leaves.map((leaf) => leaf.id));
        expect(resolveStepParameterKeys(buildStepParameterTree(model), [...values.keys()]).dropped).toEqual([]);
    });

    it("types card values as the tool form would", () => {
        expect(typedParameterValue({ name: "p", type: "float" }, "0.9")).toBe(0.9);
        expect(typedParameterValue({ name: "p", type: "integer" }, "5")).toBe(5);
        expect(typedParameterValue({ name: "p", type: "boolean" }, "true")).toBe(true);
        expect(typedParameterValue({ name: "p", type: "text" }, "x")).toBe("x");
    });

    it("parses the route argument", () => {
        expect(parseStepParameterOverridesArg(undefined)).toEqual({});
        expect(parseStepParameterOverridesArg('{"1": {"threshold": null}}')).toEqual({
            overrides: { 1: { threshold: null } },
        });
        expect(parseStepParameterOverridesArg("[1]").error).toContain("JSON object");
        expect(parseStepParameterOverridesArg("{").error).toContain("not valid JSON");
    });
});
