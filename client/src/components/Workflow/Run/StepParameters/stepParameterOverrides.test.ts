import { describe, expect, it } from "vitest";

import {
    buildStepParameterOverrides,
    parseStepParameterOverridesArg,
    stepParameterOverrideValues,
} from "./stepParameterOverrides";

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

    it("parses the route argument", () => {
        expect(parseStepParameterOverridesArg(undefined)).toEqual({});
        expect(parseStepParameterOverridesArg('{"1": {"threshold": null}}')).toEqual({
            overrides: { 1: { threshold: null } },
        });
        expect(parseStepParameterOverridesArg("[1]").error).toContain("JSON object");
        expect(parseStepParameterOverridesArg("{").error).toContain("not valid JSON");
    });
});
