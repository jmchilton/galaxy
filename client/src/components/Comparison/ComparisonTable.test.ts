import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { ComparisonTable as Table, DatasetCell } from "@/api/comparisons";
import { downloadBlob } from "@/utils/download";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonTable from "./ComparisonTable.vue";
import ListHeader from "@/components/Common/ListHeader.vue";

vi.mock("@/utils/download", () => ({ downloadBlob: vi.fn() }));

const TABLE = STEP_RUNS as unknown as Table;
const ALL_COLUMNS = ["version", "state", "reused", "history", ...TABLE.columns.map((c) => c.key)];
const DETAIL_STUB = { name: "ComparisonRowDetail", props: ["row", "columns", "query"], template: "<div />" };
const LINK_STUB = { name: "ItemPopoverLink", props: ["itemId", "itemSrc", "to"], template: "<a><slot /></a>" };
const DIFF_STUB = {
    name: "ComparisonDiff",
    props: ["rows", "columns", "query", "displays", "visibleColumns", "currentRunId", "requestedMetadata", "loading"],
    emits: ["close"],
    template: "<div />",
};

function mountTable(props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
    return mount(ComparisonTable as object, {
        props: { table: TABLE, visibleColumns: ALL_COLUMNS, ...props },
        global: {
            ...localVue,
            stubs: {
                ...localVue.stubs,
                ComparisonRowDetail: DETAIL_STUB,
                ItemPopoverLink: LINK_STUB,
                ComparisonDiff: DIFF_STUB,
            },
        },
    });
}

function headerTexts(wrapper: ReturnType<typeof mountTable>) {
    return wrapper.findAll("thead th").map((th) => th.text().replace(/\s+/g, " ").trim());
}

async function selectRow(wrapper: ReturnType<typeof mountTable>, index: number) {
    await wrapper.findAll("tbody tr")[index]!.find(".g-table-select-column input").setValue(true);
}

function selectedRows(wrapper: ReturnType<typeof mountTable>) {
    return wrapper.findAll("tbody tr").map((tr) => tr.classes().includes("g-table-row-selected"));
}

function columnHeader(wrapper: ReturnType<typeof mountTable>, index: number) {
    const th = wrapper.findAll("thead th")[index]!;
    return [th.find(".comparison-role").text(), th.find(".comparison-column-label").text()];
}

describe("ComparisonTable", () => {
    it("renders run fields, then role-badged columns, one row per run", () => {
        const wrapper = mountTable();
        const headers = headerTexts(wrapper);
        expect(headers.slice(2, 7)).toEqual(["Invoked", "Version", "State", "Reused", "History"]);
        expect(columnHeader(wrapper, 7)).toEqual(["in", "input1"]);
        expect(columnHeader(wrapper, 8)).toEqual(["out", "out_file1"]);
        const rows = wrapper.findAll("tbody tr");
        expect(rows.map((tr) => tr.attributes("data-pk"))).toEqual(TABLE.rows.map((r) => r.run.id));
    });

    it("renders each cell type from the real response shape", () => {
        const rows = mountTable().findAll("tbody tr");
        // not yet scheduled: missing cells, version 2
        expect(rows[0]!.text()).toContain("not run yet");
        expect(rows[0]!.text()).toContain("v2");
        expect(
            rows[1]!.findAllComponents(LINK_STUB).map((l: { props: (key: string) => unknown }) => l.props("itemSrc")),
        ).toEqual(["hda", "hda"]);
        // mapped step: collections and the batch note
        expect(
            rows[4]!.findAllComponents(LINK_STUB).map((l: { props: (key: string) => unknown }) => l.props("itemSrc")),
        ).toEqual(["hdca", "hdca"]);
        expect(rows[4]!.text()).toContain("mapped over 3 jobs");
        expect(rows[4]!.text()).toContain("partly reused");
        expect(rows[5]!.text()).toContain("deleted history");
    });

    it("names run states as the invocation view does", () => {
        const states = mountTable()
            .findAll("tbody tr")
            .map((tr) => tr.findAll("td")[4]!.text());
        expect(states).toEqual(["new", "successful", "successful", "successful", "successful", "successful"]);
    });

    it("highlights the current run", () => {
        const current = TABLE.rows[2]!.run.id;
        const rows = mountTable({ currentRunId: current }).findAll("tbody tr");
        expect(rows.map((tr) => tr.classes().includes("comparison-current-row"))).toEqual([
            false,
            false,
            true,
            false,
            false,
            false,
        ]);
        expect(rows[2]!.text()).toContain("this run");
        expect(rows[1]!.text()).not.toContain("this run");
    });

    it("highlights the current run's column when transposed", () => {
        const wrapper = mountTable({ transpose: true, currentRunId: TABLE.rows[2]!.run.id });
        const isCurrent = (cell: { classes: () => string[] }) => cell.classes().includes("comparison-current-cell");
        expect(wrapper.findAll("thead th").map(isCurrent)).toEqual([false, false, false, true, false, false, false]);
        wrapper.findAll("tbody tr").forEach((line) => {
            expect(line.findAll("td").map(isCurrent)).toEqual([false, false, false, true, false, false, false]);
        });
        expect(wrapper.findAll("thead th")[3]!.text()).toContain("this run");
    });

    it("marks cells that differ from the current run's", () => {
        const current = TABLE.rows[1]!.run.id;
        const changed = (cell: { classes: () => string[] }) => cell.classes().includes("comparison-cell-changed");
        const rows = mountTable({ currentRunId: current }).findAll("tbody tr");
        // input then output; outputs shown as links are never compared
        expect(rows.map((tr) => tr.findAll("td").slice(-2).map(changed))).toEqual([
            [true, true],
            [false, false],
            [true, false],
            [true, false],
            [true, false],
            [true, false],
        ]);
        expect(rows[0]!.findAll("td").slice(0, -2).some(changed)).toBe(false);
        expect(rows[2]!.find(".comparison-cell-changed [title='Differs from the run you are viewing']").exists()).toBe(
            true,
        );
    });

    it("compares cells by their display", () => {
        const rows = mountTable({
            currentRunId: TABLE.rows[1]!.run.id,
            columnDisplay: { "output:out_file1": "meta:data_lines" },
        }).findAll("tbody tr");
        const outputChanged = rows.map((tr) => tr.findAll("td").at(-1)!.classes().includes("comparison-cell-changed"));
        // not run, the same line count, a collection, and a dataset without the element
        expect(outputChanged).toEqual([true, false, false, false, true, true]);
    });

    it("marks changed cells in the run's column when transposed", () => {
        const wrapper = mountTable({ transpose: true, currentRunId: TABLE.rows[1]!.run.id });
        const inputLine = wrapper.find("tbody tr[data-pk='input:input1']");
        expect(inputLine.findAll("td").map((td) => td.classes().includes("comparison-cell-changed"))).toEqual([
            false,
            true,
            false,
            true,
            true,
            true,
            true,
        ]);
    });

    it("marks nothing without a current run", () => {
        expect(mountTable().find(".comparison-cell-changed").exists()).toBe(false);
    });

    it("links rows to the invocation with the step selected", () => {
        const link = mountTable().find("tbody tr .comparison-run-link");
        expect(link.attributes("href")).toContain(
            `/workflows/invocations/${TABLE.rows[0]!.run.id}?step_label=second_cat`,
        );
    });

    it("mounts the row detail only while a row is expanded", async () => {
        const wrapper = mountTable();
        expect(wrapper.findAllComponents(DETAIL_STUB)).toHaveLength(0);
        const toggle = wrapper.findAll(".comparison-expand")[1]!;
        expect(toggle.attributes("aria-expanded")).toBe("false");
        expect(toggle.attributes("aria-label")).toBe("Show run details");
        await toggle.trigger("click");
        const details = wrapper.findAllComponents(DETAIL_STUB);
        expect(details).toHaveLength(1);
        expect(details[0]!.props("row")).toEqual(TABLE.rows[1]);
        expect(wrapper.findAll(".comparison-expand")[1]!.attributes("aria-expanded")).toBe("true");
        expect(wrapper.findAll(".comparison-expand")[1]!.attributes("aria-label")).toBe("Hide run details");
        await wrapper.findAll(".comparison-expand")[1]!.trigger("click");
        expect(wrapper.findAllComponents(DETAIL_STUB)).toHaveLength(0);
    });

    it("collapses expanded rows when the page changes", async () => {
        const wrapper = mountTable();
        await wrapper.findAll(".comparison-expand")[1]!.trigger("click");
        expect(wrapper.findAllComponents(DETAIL_STUB)).toHaveLength(1);
        await wrapper.setProps({ table: { ...TABLE, rows: TABLE.rows.slice(3) } } as object);
        expect(wrapper.findAllComponents(DETAIL_STUB)).toHaveLength(0);
        expect(wrapper.findAll(".comparison-expand").map((b) => b.attributes("aria-expanded"))).toEqual([
            "false",
            "false",
            "false",
        ]);
    });

    it("transposes: one line per field and column, runs across", () => {
        const wrapper = mountTable({ transpose: true });
        expect(wrapper.findAll("thead th")).toHaveLength(1 + TABLE.rows.length);
        const lines = wrapper.findAll("tbody tr");
        expect(lines.map((tr) => tr.attributes("data-pk"))).toEqual(ALL_COLUMNS);
        lines.forEach((line) => expect(line.findAll("td")).toHaveLength(1 + TABLE.rows.length));
        expect(wrapper.find("[title='No cell for this run']").exists()).toBe(false);
        const outputLine = lines[5]!;
        expect(outputLine.findAll("td")[1]!.text()).toContain("not run yet");
        expect(outputLine.findAll("td")[2]!.text()).toContain(
            (TABLE.rows[1]!.cells["output:out_file1"] as DatasetCell).name,
        );
        expect(wrapper.findAll(".comparison-expand")).toHaveLength(0);
    });

    it("emits the transpose toggle", async () => {
        const wrapper = mountTable();
        const button = wrapper.find(".comparison-transpose");
        expect(button.attributes("aria-pressed")).toBe("false");
        await button.trigger("click");
        expect(wrapper.emitted("update:transpose")).toEqual([[true]]);
    });

    it("hides columns that are not visible and forwards the chooser's events", async () => {
        const wrapper = mountTable({ visibleColumns: ["state", "output:out_file1"] });
        const headers = headerTexts(wrapper);
        expect(headers.slice(2, 4)).toEqual(["Invoked", "State"]);
        expect(columnHeader(wrapper, 4)).toEqual(["out", "out_file1"]);
        expect(headers).toHaveLength(5);
        const header = wrapper.findComponent(ListHeader);
        expect((header.props("columnOptions") as { key: string }[]).map((o: { key: string }) => o.key)).toEqual(
            ALL_COLUMNS,
        );
        header.vm.$emit("toggle-column", "input:input1");
        header.vm.$emit("reset-columns");
        expect(wrapper.emitted("toggle-column")).toEqual([["input:input1"]]);
        expect(wrapper.emitted("reset-columns")).toHaveLength(1);
    });

    it("switches a column to a metadata element", async () => {
        const wrapper = mountTable();
        const output = wrapper.findAll("thead th")[8]!;
        expect(output.find(".comparison-showing").text()).toBe("name");
        const items = output.findAll("[role='menuitemradio']");
        expect(items.map((i) => i.text())).toEqual(["Name with popover", "Value", "data_lines", "dbkey"]);
        expect(items.map((i) => i.classes().includes("active"))).toEqual([true, false, false, false]);
        await items[2]!.trigger("click");
        expect(wrapper.emitted("update:columnDisplay")).toEqual([[{ "output:out_file1": "meta:data_lines" }]]);
    });

    it("shows the requested metadata element in cells", () => {
        const rows = mountTable({ columnDisplay: { "output:out_file1": "meta:data_lines" } }).findAll("tbody tr");
        expect(rows[1]!.findAll("td")[8]!.text()).toBe("1");
    });

    it("selects two runs and compares them side by side", async () => {
        const wrapper = mountTable({ currentRunId: TABLE.rows[1]!.run.id });
        const compare = () => wrapper.find(".comparison-compare-selected");
        expect(compare().attributes("aria-disabled")).toBeDefined();
        expect(compare().text()).toContain("0/2");
        await selectRow(wrapper, 3);
        await selectRow(wrapper, 1);
        expect(compare().attributes("aria-disabled")).toBeUndefined();
        expect(compare().text()).toContain("2/2");
        expect(wrapper.findComponent(DIFF_STUB).exists()).toBe(false);
        await compare().trigger("click");
        const diff = wrapper.findComponent(DIFF_STUB);
        // in table order, whatever order they were picked in
        expect(diff.props("rows")).toEqual([TABLE.rows[1], TABLE.rows[3]]);
        expect(diff.props("displays")).toEqual({ "input:input1": "link", "output:out_file1": "link" });
        expect(diff.props("visibleColumns")).toEqual(ALL_COLUMNS);
        expect(diff.props("currentRunId")).toBe(TABLE.rows[1]!.run.id);
        expect(compare().attributes("aria-expanded")).toBe("true");
        expect(compare().attributes("aria-disabled")).toBeUndefined();
        expect(compare().text()).toBe("Hide comparison");
        diff.vm.$emit("close");
        await wrapper.vm.$nextTick();
        expect(wrapper.findComponent(DIFF_STUB).exists()).toBe(false);
        expect(compare().attributes("aria-expanded")).toBe("false");
        expect(compare().text()).toContain("Compare selected (2/2)");
    });

    it("keeps the two runs selected last", async () => {
        const wrapper = mountTable();
        for (const index of [0, 1, 2]) {
            await selectRow(wrapper, index);
        }
        expect(selectedRows(wrapper)).toEqual([false, true, true, false, false, false]);
    });

    it("keeps the selection when transposed, with a checkbox per run", async () => {
        const wrapper = mountTable();
        await selectRow(wrapper, 0);
        await selectRow(wrapper, 2);
        await wrapper.setProps({ transpose: true } as object);
        const boxes = wrapper.findAll("thead .comparison-select-run input");
        expect(boxes.map((box) => (box.element as HTMLInputElement).checked)).toEqual([
            true,
            false,
            true,
            false,
            false,
            false,
        ]);
        await boxes[0]!.setValue(false);
        expect(wrapper.find(".comparison-compare-selected").attributes("aria-disabled")).toBeDefined();
        await wrapper.setProps({ transpose: false } as object);
        expect(selectedRows(wrapper)).toEqual([false, false, true, false, false, false]);
    });

    it("drops selected runs that leave the page", async () => {
        const wrapper = mountTable();
        await selectRow(wrapper, 0);
        await selectRow(wrapper, 4);
        await wrapper.find(".comparison-compare-selected").trigger("click");
        await wrapper.setProps({ table: { ...TABLE, rows: TABLE.rows.slice(1) } } as object);
        expect(selectedRows(wrapper)).toEqual([false, false, false, true, false]);
        expect(wrapper.findComponent(DIFF_STUB).exists()).toBe(false);
    });

    it("exports the page as shown, as CSV or TSV", async () => {
        const wrapper = mountTable({
            visibleColumns: ["state", "output:out_file1"],
            columnDisplay: { "output:out_file1": "meta:data_lines" },
        });
        vi.mocked(downloadBlob).mockClear();
        await wrapper.find(".comparison-export-csv").trigger("click");
        const [blob, filename] = vi.mocked(downloadBlob).mock.calls[0]!;
        expect(filename).toBe("runs_of_second_cat_1-6.csv");
        const lines = (await blob.text()).split("\r\n");
        expect(lines[0]).toBe("﻿Invoked,State,out_file1 (output)");
        expect(lines[2]).toBe(`${TABLE.rows[1]!.create_time},successful,1`);
        expect(lines).toHaveLength(TABLE.rows.length + 2);

        await wrapper.setProps({ transpose: true } as object);
        await wrapper.find(".comparison-export-tsv").trigger("click");
        const [tsv, tsvName] = vi.mocked(downloadBlob).mock.calls[1]!;
        expect(tsvName).toBe("runs_of_second_cat_1-6.tsv");
        expect((await tsv.text()).split("\r\n")[1]!.split("\t")).toEqual([
            "State",
            "new",
            "successful",
            "successful",
            "successful",
            "successful",
            "successful",
        ]);
    });

    it("explains an empty page", () => {
        const wrapper = mountTable({ table: { ...TABLE, rows: [] }, emptyMessage: "No runs yet." });
        expect(wrapper.text()).toContain("No runs yet.");
        expect(wrapper.find("table").exists()).toBe(false);
    });
});
