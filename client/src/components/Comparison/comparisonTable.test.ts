import { describe, expect, it } from "vitest";

import type { ComparisonColumn, ComparisonQuery, ComparisonRow, ComparisonTable, MissingCell } from "@/api/comparisons";

import {
    defaultDisplay,
    displayOptions,
    fieldKeys,
    formatValue,
    missingText,
    requestedMetadata,
    rowJob,
    runLink,
    transpose,
    untranspose,
    versionLabel,
} from "./comparisonTable";
import STEP_RUNS from "./test-data/step_runs.json";

const TABLE = STEP_RUNS as unknown as ComparisonTable;

function column(overrides: Partial<ComparisonColumn>): ComparisonColumn {
    return { key: "output:x", label: "x", role: "output", duplicate: false, metadata_keys: [], ...overrides };
}

function row(overrides: Partial<ComparisonRow>): ComparisonRow {
    return { ...TABLE.rows[1]!, ...overrides };
}

describe("transpose", () => {
    it("round trips the fixture", () => {
        expect(untranspose(transpose(TABLE))).toEqual({ columns: TABLE.columns, rows: TABLE.rows });
    });

    it("keeps the grid uniform: every column has a cell for every run", () => {
        const transposed = transpose(TABLE);
        TABLE.columns.forEach((c) => {
            const cells = transposed.cells[c.key]!;
            expect(cells).toHaveLength(TABLE.rows.length);
            cells.forEach((cell, index) => expect(cell).toBe(TABLE.rows[index]!.cells[c.key]));
            expect(cells.every(Boolean)).toBe(true);
        });
    });
});

describe("display", () => {
    it("defaults datasets and collections to links", () => {
        TABLE.columns.forEach((c) => expect(defaultDisplay(c, TABLE.rows)).toBe("link"));
    });

    it("defaults parameters and inlined values to values", () => {
        expect(defaultDisplay(column({ role: "parameter" }), [])).toBe("value");
        const valueRow = row({ cells: { "output:n": { type: "value", value: 42, source: "expression_json" } } });
        expect(defaultDisplay(column({ key: "output:n" }), [valueRow])).toBe("value");
    });

    it("offers the column's metadata keys, and no link for parameters", () => {
        const output = TABLE.columns[1]!;
        expect(displayOptions(output, TABLE.rows).map((o) => [o.display, Boolean(o.disabled)])).toEqual([
            ["link", false],
            ["value", true],
            ["meta:data_lines", false],
            ["meta:dbkey", false],
        ]);
        const parameter = displayOptions(column({ role: "parameter", metadata_keys: ["x"] }), []);
        expect(parameter.map((o) => [o.display, Boolean(o.disabled)])).toEqual([
            ["link", true],
            ["value", false],
        ]);
    });

    it("requests each displayed metadata element once", () => {
        expect(requestedMetadata({ a: "meta:data_lines", b: "link", c: "meta:columns", d: "meta:data_lines" })).toEqual(
            ["columns", "data_lines"],
        );
    });

    it("gives unique, slot-safe field keys", () => {
        const keys = fieldKeys([column({ key: "input:anno|ref" }), column({ key: "output:anno|ref" })]);
        expect(new Set(Object.values(keys)).size).toBe(2);
        Object.values(keys).forEach((key) => expect(key).toMatch(/^[a-z0-9]+$/));
    });
});

describe("missingText", () => {
    const cases: [MissingCell["reason"], string][] = [
        ["not_in_version", "not in v2"],
        ["not_run_yet", "not run yet"],
        ["skipped", "skipped"],
        ["no_output", "no output"],
        ["inaccessible", "no access"],
    ];
    it.each(cases)("%s reads %s", (reason, text) => {
        expect(missingText({ type: "missing", reason }, { version: 1 })).toBe(text);
    });

    it("names the tool version in mode 3", () => {
        expect(missingText({ type: "missing", reason: "not_in_version" }, { tool_version: "0.2" })).toBe("not in 0.2");
    });

    it("renders versions 1-based", () => {
        expect(versionLabel(0)).toBe("v1");
        expect(versionLabel(null)).toBe("");
    });
});

describe("formatValue", () => {
    it("formats scalars, null and JSON", () => {
        expect(formatValue(42)).toBe("42");
        expect(formatValue(false)).toBe("false");
        expect(formatValue(null)).toBe("null");
        expect(formatValue("a")).toBe("a");
        expect(formatValue({ a: [1] })).toBe('{\n  "a": [\n    1\n  ]\n}');
    });
});

describe("runLink", () => {
    const invocationRow = row({ run: { model: "WorkflowInvocation", id: "inv1", state: "scheduled" } });

    it("selects the step in mode 1, encoding the label", () => {
        const query = { ...TABLE.query, step_label: "count reads/2" } as ComparisonQuery;
        expect(runLink(invocationRow, query)).toBe("/workflows/invocations/inv1?step_label=count%20reads%2F2");
    });

    it("opens the invocation in mode 2", () => {
        const query = { kind: "output_runs", workflow_id: "w" } as ComparisonQuery;
        expect(runLink(invocationRow, query)).toBe("/workflows/invocations/inv1");
    });

    it("opens the job, or a batch's first job, in mode 3", () => {
        const query = { kind: "tool_runs", tool_id: "cat1" } as ComparisonQuery;
        expect(runLink(row({ run: { model: "Job", id: "job1", state: "ok" } }), query)).toBe("/jobs/job1/view");
        const batch = row({
            run: {
                model: "ImplicitCollectionJobs",
                id: "icj1",
                representative_job_id: "job2",
                job_count: 3,
                populated_state: "ok",
                states: { ok: 3 },
            },
        });
        expect(runLink(batch, query)).toBe("/jobs/job2/view");
    });
});

describe("rowJob", () => {
    it("reads the step job, a batch's first job, or nothing before the step runs", () => {
        const [notRun, plain, , , mapped] = TABLE.rows;
        expect(rowJob(notRun!)).toBeUndefined();
        expect(rowJob(plain!)).toEqual({ jobId: plain!.step_job!.id });
        expect(rowJob(mapped!)).toEqual({ jobId: "cb227cec8ca83994", jobCount: 3 });
    });
});
