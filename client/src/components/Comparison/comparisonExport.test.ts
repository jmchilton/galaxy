import { describe, expect, it } from "vitest";

import type { ComparisonCell, ComparisonQuery, ComparisonRow, DatasetCell } from "@/api/comparisons";

import { cellText, exportBlob, exportFilename, exportLines, spreadsheetSafe, toDelimited } from "./comparisonExport";
import { META_FIELD_SPECS } from "./comparisonUtils";
import { STEP_RUNS_TABLE } from "./test-utils";

const TABLE = STEP_RUNS_TABLE;
const [NOT_RUN, V2_RUN] = TABLE.rows as [ComparisonRow, ComparisonRow];
const MAPPED = TABLE.rows[4]!;
const link = () => "link" as const;

describe("cellText", () => {
    it("writes what each display shows", () => {
        const input = V2_RUN.cells["input:input1"];
        expect(cellText(input, V2_RUN, "link")).toBe("6: Concatenate multiple datasets or collections on dataset 1");
        expect(cellText(input, V2_RUN, "meta:data_lines")).toBe("1");
        expect(cellText(input, V2_RUN, "meta:dbkey")).toBe("");
        expect(cellText(MAPPED.cells["input:input1"], MAPPED, "meta:data_lines")).toBe("list · 3");
        expect(cellText(NOT_RUN.cells["input:input1"], NOT_RUN, "link")).toBe("not run yet");
        expect(cellText(undefined, NOT_RUN, "link")).toBe("");
    });

    it("writes every dataset of a multiple input", () => {
        const input = V2_RUN.cells["input:input1"] as DatasetCell;
        const second = { ...input, hid: 9, name: "second", metadata: { data_lines: 4 } };
        const list: ComparisonCell = {
            type: "dataset_list",
            items: [input, second, { type: "missing", reason: "inaccessible" }],
        };
        expect(cellText(list, V2_RUN, "link")).toBe(`6: ${input.name}; 9: second; no access`);
        expect(cellText(list, V2_RUN, "meta:data_lines")).toBe("1; 4; no access");
    });

    it("writes values on one line", () => {
        const cell = { type: "value", value: { a: [1, 2] }, source: "parameter" } as const;
        expect(cellText(cell, V2_RUN, "value")).toBe('{"a":[1,2]}');
        expect(cellText({ ...cell, value: null }, V2_RUN, "value")).toBe("null");
    });
});

describe("META_FIELD_SPECS text", () => {
    it("writes run fields as text, with the full time", () => {
        expect(META_FIELD_SPECS.invoked.text(V2_RUN)).toBe(V2_RUN.create_time);
        expect(META_FIELD_SPECS.version.text(V2_RUN)).toBe("v2");
        expect(META_FIELD_SPECS.state.text(V2_RUN)).toBe("successful");
        expect(META_FIELD_SPECS.reused.text(V2_RUN)).toBe("no");
        expect(META_FIELD_SPECS.history.text(V2_RUN)).toBe("test_history");
    });
});

describe("exportLines", () => {
    const visible = ["version", "output:out_file1"];

    it("writes runs as rows, with only the visible fields and columns", () => {
        const lines = exportLines(TABLE, { visibleColumns: visible, transpose: false, displayOf: link });
        expect(lines[0]).toEqual(["Invoked", "Version", "out_file1 (output)"]);
        expect(lines[2]).toEqual([
            V2_RUN.create_time,
            "v2",
            "7: Concatenate multiple datasets or collections on dataset 6",
        ]);
        expect(lines).toHaveLength(TABLE.rows.length + 1);
    });

    it("writes runs as columns when transposed", () => {
        const lines = exportLines(TABLE, { visibleColumns: visible, transpose: true, displayOf: link });
        expect(lines.map((line) => line[0])).toEqual(["Invoked", "Version", "out_file1 (output)"]);
        expect(lines[1]!.slice(1, 3)).toEqual(["v2", "v2"]);
        expect(lines[0]).toHaveLength(TABLE.rows.length + 1);
    });

    it("honours each column's display", () => {
        const lines = exportLines(TABLE, {
            visibleColumns: visible,
            transpose: false,
            displayOf: () => "meta:data_lines",
        });
        expect(lines[2]![2]).toBe("1");
    });

    it("writes an empty input as not supplied and an empty output as no output", () => {
        const empty = { type: "missing", reason: "no_output" } as const;
        const row = { ...V2_RUN, cells: { ...V2_RUN.cells, "input:input1": empty, "output:out_file1": empty } };
        const table = { ...TABLE, rows: [row] };
        const lines = exportLines(table, {
            visibleColumns: ["input:input1", "output:out_file1"],
            transpose: false,
            displayOf: link,
        });
        expect(lines[1]!.slice(-2)).toEqual(["not supplied", "no output"]);
    });
});

describe("toDelimited", () => {
    it("quotes CSV fields that need it", () => {
        expect(toDelimited([["a", 'say "hi"', "x,y", "two\nlines"]], "csv")).toBe(
            'a,"say ""hi""","x,y","two\nlines"\r\n',
        );
    });

    it("keeps TSV fields on one line", () => {
        expect(
            toDelimited(
                [
                    ["a\tb", "c\r\nd"],
                    ["e", "f"],
                ],
                "tsv",
            ),
        ).toBe("a b\tc d\r\ne\tf\r\n");
    });

    it("escapes formula-like fields in both formats", () => {
        expect(toDelimited([["=1+1", "@x"]], "csv")).toBe("'=1+1,'@x\r\n");
        expect(toDelimited([["\tx", "+x"]], "tsv")).toBe("' x\t'+x\r\n");
    });
});

describe("spreadsheetSafe", () => {
    it("prefixes text a spreadsheet would read as a formula", () => {
        for (const text of ["=SUM(A1)", "+x", "-x", "-", "@x", "\tx", "\rx"]) {
            expect(spreadsheetSafe(text)).toBe(`'${text}`);
        }
    });

    it("keeps numbers and plain text as they are", () => {
        for (const text of ["-1", "-0.5", "+2", "1e5", "-1.5E-3", ".5", "a=b", "", "v2"]) {
            expect(spreadsheetSafe(text)).toBe(text);
        }
    });
});

describe("exportBlob", () => {
    const bytes = async (blob: Blob) => [...new Uint8Array(await blob.arrayBuffer())].slice(0, 3);

    it("marks CSV as UTF-8 for spreadsheets, not TSV", async () => {
        expect(await bytes(exportBlob([["é"]], "csv"))).toEqual([0xef, 0xbb, 0xbf]);
        expect(await bytes(exportBlob([["a"]], "tsv"))).toEqual([0x61, 0x0d, 0x0a]);
    });
});

describe("exportFilename", () => {
    it("names the comparison and the rows of the page", () => {
        expect(exportFilename(TABLE.query, 5, "csv")).toBe("runs_of_second_cat_1-5.csv");
        const tool = { kind: "tool_runs", tool_id: "toolshed.g2.bx.psu.edu/repos/devteam/cat/cat1/1.0", offset: 25 };
        expect(exportFilename(tool as ComparisonQuery, 3, "tsv")).toBe(
            "runs_of_toolshed.g2.bx.psu.edu_repos_devteam_cat_cat1_26-28.tsv",
        );
    });
});
