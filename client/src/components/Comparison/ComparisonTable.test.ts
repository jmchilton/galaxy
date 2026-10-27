import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ComparisonTable as Table } from "@/api/comparisons";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonTable from "./ComparisonTable.vue";
import ListHeader from "@/components/Common/ListHeader.vue";

const TABLE = STEP_RUNS as unknown as Table;
const ALL_COLUMNS = ["version", "state", "reused", "history", ...TABLE.columns.map((c) => c.key)];
const DETAIL_STUB = { name: "ComparisonRowDetail", props: ["row", "columns", "query"], template: "<div />" };
const LINK_STUB = { name: "ItemPopoverLink", props: ["itemId", "itemSrc", "to"], template: "<a><slot /></a>" };

function mountTable(props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
    return mount(ComparisonTable as object, {
        props: { table: TABLE, visibleColumns: ALL_COLUMNS, ...props },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, ComparisonRowDetail: DETAIL_STUB, ItemPopoverLink: LINK_STUB },
        },
    });
}

function headerTexts(wrapper: ReturnType<typeof mountTable>) {
    return wrapper.findAll("thead th").map((th) => th.text().replace(/\s+/g, " ").trim());
}

function columnHeader(wrapper: ReturnType<typeof mountTable>, index: number) {
    const th = wrapper.findAll("thead th")[index]!;
    return [th.find(".comparison-role").text(), th.find(".comparison-column-label").text()];
}

describe("ComparisonTable", () => {
    it("renders run fields, then role-badged columns, one row per run", () => {
        const wrapper = mountTable();
        const headers = headerTexts(wrapper);
        expect(headers.slice(1, 6)).toEqual(["Invoked", "Version", "State", "Reused", "History"]);
        expect(columnHeader(wrapper, 6)).toEqual(["in", "input1"]);
        expect(columnHeader(wrapper, 7)).toEqual(["out", "out_file1"]);
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
        await toggle.trigger("click");
        const details = wrapper.findAllComponents(DETAIL_STUB);
        expect(details).toHaveLength(1);
        expect(details[0]!.props("row")).toEqual(TABLE.rows[1]);
        expect(wrapper.findAll(".comparison-expand")[1]!.attributes("aria-expanded")).toBe("true");
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
        const outputLine = lines[5]!;
        expect(outputLine.findAll("td")).toHaveLength(1 + TABLE.rows.length);
        expect(outputLine.findAll("td")[1]!.text()).toContain("not run yet");
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
        expect(headers.slice(1, 3)).toEqual(["Invoked", "State"]);
        expect(columnHeader(wrapper, 3)).toEqual(["out", "out_file1"]);
        expect(headers).toHaveLength(4);
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
        const output = wrapper.findAll("thead th")[7]!;
        expect(output.find(".comparison-showing").text()).toBe("name");
        const items = output.findAll("[role='menuitemradio']");
        expect(items.map((i) => i.text())).toEqual(["Name with popover", "Value", "data_lines", "dbkey"]);
        await items[2]!.trigger("click");
        expect(wrapper.emitted("update:columnDisplay")).toEqual([[{ "output:out_file1": "meta:data_lines" }]]);
    });

    it("shows the requested metadata element in cells", () => {
        const rows = mountTable({ columnDisplay: { "output:out_file1": "meta:data_lines" } }).findAll("tbody tr");
        expect(rows[1]!.findAll("td")[7]!.text()).toBe("1");
    });

    it("explains an empty page", () => {
        const wrapper = mountTable({ table: { ...TABLE, rows: [] }, emptyMessage: "No runs yet." });
        expect(wrapper.text()).toContain("No runs yet.");
        expect(wrapper.find("table").exists()).toBe(false);
    });
});
