import { describe, expect, it } from "vitest";

import { visitInputs } from "@/components/Form/utilities";

import {
    buildStepParameterTree,
    exposedParametersPayload,
    filterTree,
    parseStepParamValues,
    rerunHasUnexposedStepParameters,
    resolveExposureKeys,
    treeLeaves,
} from "./stepParameterTree";

function echoStepInputs() {
    return [
        { name: "input1", type: "hidden", connected: true },
        { name: "threshold", type: "float", label: "Threshold", value: "0.5" },
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
            test_param: { name: "filter_type", type: "select", label: "Filter type", value: "min" },
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
        { step_index: 1, step_type: "tool", step_name: "Echo step params", inputs: echoStepInputs() },
        {
            step_index: 2,
            step_type: "subworkflow",
            step_name: "QC",
            inputs: [{ name: "1|num_lines", type: "integer", label: "Lines", value: 3 }],
        },
    ],
};

describe("buildStepParameterTree", () => {
    it("lists exposable leaves of tool and subworkflow steps by exposure key", () => {
        const keys = treeLeaves(buildStepParameterTree(model)).map((leaf) => [leaf.key, leaf.disabledReason]);
        expect(keys).toEqual([
            ["1|threshold", undefined],
            ["1|column", "Options depend on a data input"],
            ["1|advanced|label", undefined],
            ["1|queries_0|column_name", undefined],
            ["1|queries_1|column_name", undefined],
            ["1|cond|min", undefined],
            ["2|1|num_lines", undefined],
        ]);
    });

    it("uses the same prefixed names as visitInputs", () => {
        const visited: string[] = [];
        visitInputs(echoStepInputs(), (input: any, name: string) => {
            if (!["hidden", "data", "data_collection"].includes(input.type) && name !== "cond|filter_type") {
                visited.push(`1|${name}`);
            }
        });
        const leaves = treeLeaves(buildStepParameterTree({ steps: [model.steps[1]] })).map((leaf) => leaf.key);
        expect(leaves.sort()).toEqual(visited.sort());
    });

    it("shows the conditional test value as a fixed badge", () => {
        const step = buildStepParameterTree(model)[0]!;
        const cond = step.children.find((node) => node.kind === "conditional")!;
        expect(cond.badge).toBe("min");
        expect(cond.children.map((node) => node.key)).toEqual(["1|cond|min"]);
    });

    it("filters by label and keeps ancestors", () => {
        const filtered = treeLeaves(filterTree(buildStepParameterTree(model), "query"));
        expect(filtered.map((leaf) => leaf.key)).toEqual(["1|queries_0|column_name", "1|queries_1|column_name"]);
    });
});

describe("resolveExposureKeys", () => {
    it("keeps workflow order and drops unknown and disabled keys", () => {
        const tree = buildStepParameterTree(model);
        const { leaves, dropped } = resolveExposureKeys(tree, [
            "1|cond|min",
            "1|threshold",
            "1|cond|pattern",
            "1|column",
        ]);
        expect(leaves.map((leaf) => leaf.key)).toEqual(["1|threshold", "1|cond|min"]);
        expect(dropped.map((d) => d.key)).toEqual(["1|cond|pattern", "1|column"]);
    });
});

describe("payload helpers", () => {
    it("nests exposure key values into parameters", () => {
        expect(exposedParametersPayload({ "1|threshold": 0.9, "1|cond|min": 5, "2|1|num_lines": 2 })).toEqual({
            1: { threshold: 0.9, "cond|min": 5 },
            2: { "1|num_lines": 2 },
        });
    });

    it("only gates reruns whose step parameters were not all exposed", () => {
        const parameters = { 1: { threshold: 0.9, "cond|min": 5 } };
        expect(rerunHasUnexposedStepParameters({ parameters })).toBe(true);
        expect(
            rerunHasUnexposedStepParameters({ parameters, exposed_step_parameters: ["1|threshold", "1|cond|min"] }),
        ).toBe(false);
        expect(rerunHasUnexposedStepParameters({ parameters, exposed_step_parameters: ["1|threshold"] })).toBe(true);
    });

    it("parses step_param_value entries", () => {
        expect(parseStepParamValues(["1|cond|min=5", "1|advanced|label=a=b", "bad"])).toEqual({
            "1|cond|min": "5",
            "1|advanced|label": "a=b",
        });
    });
});
