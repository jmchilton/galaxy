import { describe, expect, it } from "vitest";

import { cleanUrlQuery, comparisonPath, displayStorageKey, parseComparisonQuery } from "./comparisonQuery";

describe("parseComparisonQuery", () => {
    it.each([
        [{ kind: "nope" }, 'Unknown comparison kind "nope".'],
        [{ kind: "toString" }, 'Unknown comparison kind "toString".'],
        [{ kind: "__proto__" }, 'Unknown comparison kind "__proto__".'],
        [{}, "No comparison kind given."],
        [{ kind: "step_runs", workflow_id: "wf1" }, "A step_runs comparison needs step_label."],
        [{ kind: "output_runs" }, "A output_runs comparison needs workflow_id."],
        [{ kind: "tool_runs", tool_id: "cat1", state: "ok" }, "A tool_runs comparison does not take state."],
        [
            { kind: "tool_runs", tool_id: "cat1", output_labels: "a", constructor: "x" },
            "A tool_runs comparison does not take output_labels, constructor.",
        ],
    ])("rejects %j", (query, error) => {
        expect(parseComparisonQuery(query)).toEqual({ error });
    });

    it("parses each value by its parameter kind", () => {
        expect(
            parseComparisonQuery({
                kind: "tool_runs",
                tool_id: "cat1",
                limit: "10",
                sort_desc: "false",
                include_workflow_jobs: "true",
                states: "ok",
                tool_versions: ["1.0", null, "2.0"],
            }),
        ).toEqual({
            kind: "tool_runs",
            params: {
                tool_id: "cat1",
                limit: 10,
                sort_desc: false,
                include_workflow_jobs: true,
                states: ["ok"],
                tool_versions: ["1.0", "2.0"],
            },
        });
    });

    it("passes malformed numbers and booleans through for the server to reject", () => {
        expect(parseComparisonQuery({ kind: "tool_runs", tool_id: "cat1", limit: "1.5", sort_desc: "yes" })).toEqual({
            kind: "tool_runs",
            params: { tool_id: "cat1", limit: "1.5", sort_desc: "yes" },
        });
    });
});

describe("cleanUrlQuery", () => {
    it("drops unset values and empty lists and stringifies scalars", () => {
        expect(cleanUrlQuery({ a: undefined, b: null, c: [], d: 0, e: false, f: ["x"] })).toEqual({
            d: "0",
            e: "false",
            f: ["x"],
        });
    });
});

describe("comparisonPath", () => {
    it("repeats list keys rather than joining on commas", () => {
        expect(comparisonPath("output_runs", { workflow_id: "wf1", output_labels: ["a,b", "n"], states: [] })).toBe(
            "/comparisons?kind=output_runs&workflow_id=wf1&output_labels=a%2Cb&output_labels=n",
        );
    });
});

describe("displayStorageKey", () => {
    it("names a comparison by what it compares, sharing one key across Tool Shed versions", () => {
        expect(displayStorageKey({ kind: "step_runs", workflow_id: "wf1", step_label: "s" })).toBe("step_runs:wf1:s");
        expect(displayStorageKey({ kind: "output_runs", workflow_id: "wf1" })).toBe("output_runs:wf1");
        expect(
            displayStorageKey({ kind: "tool_runs", tool_id: "toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1/2.0" }),
        ).toBe("tool_runs:toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1");
    });
});
