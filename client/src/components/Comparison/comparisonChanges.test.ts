import { describe, expect, it } from "vitest";

import type { ComparisonCell, ComparisonColumn, ComparisonRow, ComparisonTable, DatasetCell } from "@/api/comparisons";

import { changedCells, compareCells, compareMeta } from "./comparisonChanges";
import STEP_RUNS from "./test-data/step_runs.json";

const TABLE = STEP_RUNS as unknown as ComparisonTable;
const [NOT_RUN, V2_RUN, V1_RUN] = TABLE.rows as [ComparisonRow, ComparisonRow, ComparisonRow];
const INPUT = TABLE.columns[0]!;
const OUTPUT = TABLE.columns[1]!;

function dataset(overrides: Partial<DatasetCell> = {}): DatasetCell {
    return { ...(V2_RUN.cells["input:input1"] as DatasetCell), ...overrides };
}

function value(value: unknown): ComparisonCell {
    return { type: "value", value, source: "parameter" };
}

function parameter(key = "parameter:p"): ComparisonColumn {
    return { key, label: "p", role: "parameter", duplicate: false, metadata_keys: [] };
}

describe("compareCells", () => {
    it("compares inputs shown as links by item id", () => {
        expect(compareCells(dataset(), dataset(), INPUT, "link")).toBe("same");
        expect(compareCells(dataset(), dataset({ id: "other" }), INPUT, "link")).toBe("differs");
    });

    it("leaves outputs shown as links uncompared, since every run makes new items", () => {
        expect(compareCells(dataset(), dataset({ id: "other" }), OUTPUT, "link")).toBe("uncompared");
    });

    it("compares a metadata display by the element's value", () => {
        const one = dataset({ metadata: { data_lines: 1 } });
        expect(compareCells(one, dataset({ id: "x", metadata: { data_lines: 1 } }), OUTPUT, "meta:data_lines")).toBe(
            "same",
        );
        expect(compareCells(one, dataset({ metadata: { data_lines: 2 } }), OUTPUT, "meta:data_lines")).toBe("differs");
        expect(compareCells(one, dataset({ metadata: {} }), OUTPUT, "meta:data_lines")).toBe("differs");
    });

    it("compares values deeply, ignoring key order", () => {
        expect(compareCells(value({ a: 1, b: [1, 2] }), value({ b: [1, 2], a: 1 }), parameter(), "value")).toBe("same");
        expect(compareCells(value({ a: 1 }), value({ a: 2 }), parameter(), "value")).toBe("differs");
        expect(compareCells(value(1), value("1"), parameter(), "value")).toBe("differs");
    });

    it("counts missing against present, and differing reasons, as differences", () => {
        const notRun = NOT_RUN.cells["output:out_file1"];
        expect(compareCells(notRun, dataset(), OUTPUT, "link")).toBe("differs");
        expect(compareCells(notRun, { type: "missing", reason: "skipped" }, OUTPUT, "link")).toBe("differs");
        expect(compareCells(notRun, notRun, OUTPUT, "link")).toBe("same");
        expect(compareCells(undefined, dataset(), INPUT, "link")).toBe("differs");
    });

    it("compares a multiple input's datasets in order", () => {
        const list = (...items: DatasetCell[]): ComparisonCell => ({ type: "dataset_list", items });
        const [a, b] = [dataset({ id: "a" }), dataset({ id: "b" })];
        expect(compareCells(list(a, b), list(a, b), INPUT, "link")).toBe("same");
        expect(compareCells(list(a, b), list(b, a), INPUT, "link")).toBe("differs");
        expect(compareCells(list(a, b), list(a, b, b), INPUT, "link")).toBe("differs");
        const lines = (n: number) => dataset({ metadata: { data_lines: n } });
        expect(compareCells(list(lines(1), lines(2)), list(lines(1), lines(2)), INPUT, "meta:data_lines")).toBe("same");
        expect(compareCells(list(lines(1), lines(2)), list(lines(1), lines(3)), INPUT, "meta:data_lines")).toBe(
            "differs",
        );
    });
});

describe("compareMeta", () => {
    it("compares version, state and history, never the run's own time", () => {
        expect(compareMeta("version", V2_RUN, V1_RUN)).toBe("differs");
        expect(compareMeta("state", V2_RUN, V1_RUN)).toBe("same");
        expect(compareMeta("history", V2_RUN, V1_RUN)).toBe("same");
        expect(compareMeta("invoked", V2_RUN, V1_RUN)).toBe("uncompared");
    });
});

describe("changedCells", () => {
    const display = () => "link" as const;

    it("marks the cells of other runs that differ from the current run's", () => {
        const changed = changedCells(TABLE.rows, TABLE.columns, display, V2_RUN.run.id);
        expect(changed.get(V2_RUN.run.id)).toBeUndefined();
        expect([...changed.get(V1_RUN.run.id)!]).toEqual(["input:input1"]);
        expect([...changed.get(NOT_RUN.run.id)!]).toEqual(["input:input1", "output:out_file1"]);
    });

    it("marks nothing without a current run on the page", () => {
        expect(changedCells(TABLE.rows, TABLE.columns, display, undefined).size).toBe(0);
        expect(changedCells(TABLE.rows, TABLE.columns, display, "elsewhere").size).toBe(0);
    });
});
