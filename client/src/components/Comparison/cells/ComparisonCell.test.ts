import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type {
    CollectionCell,
    ComparisonCell as Cell,
    ComparisonTable,
    DatasetCell,
    MissingCell,
} from "@/api/comparisons";

import type { CellDisplay } from "../comparisonUtils";
import STEP_RUNS from "../test-data/step_runs.json";

import ComparisonCell from "./ComparisonCell.vue";

const TABLE = STEP_RUNS as unknown as ComparisonTable;
const DATASET = TABLE.rows[1]!.cells["output:out_file1"] as DatasetCell;
const COLLECTION = TABLE.rows[4]!.cells["output:out_file1"] as CollectionCell;
const LINK_STUB = {
    name: "ItemPopoverLink",
    props: ["itemId", "itemSrc", "to", "linkClass"],
    template: "<a class='item-link'><slot /></a>",
};

function mountCell(
    cell: Cell | undefined,
    display: CellDisplay = "link",
    requestedMetadata: string[] = [],
    loading = false,
) {
    const localVue = getLocalVue();
    return mount(ComparisonCell as object, {
        props: { cell, row: { version: 1 }, display, requestedMetadata, loading },
        global: { ...localVue, stubs: { ...localVue.stubs, ItemPopoverLink: LINK_STUB, FontAwesomeIcon: true } },
    });
}

describe("ComparisonCell links", () => {
    it("links a dataset by hid and name with a popover", () => {
        const wrapper = mountCell(DATASET);
        const link = wrapper.findComponent(LINK_STUB);
        expect(link.props("itemId")).toBe(DATASET.id);
        expect(link.props("itemSrc")).toBe("hda");
        expect(link.props("to")).toBeUndefined();
        expect(link.text()).toBe(`${DATASET.hid}: ${DATASET.name}`);
        expect(wrapper.find(".badge").exists()).toBe(false);
    });

    it("marks a dataset that is not ok with its state icon", () => {
        expect(mountCell(DATASET).find(".comparison-item-state").exists()).toBe(false);
        const state = mountCell({ ...DATASET, state: "error" }).find(".comparison-item-state");
        expect(state.attributes("title")).toBe("failed");
        expect(state.text()).toBe("");
    });

    it("links a collection to its history", () => {
        const link = mountCell(COLLECTION).findComponent(LINK_STUB);
        expect(link.props("itemSrc")).toBe("hdca");
        expect(link.props("to")).toBe(`/histories/view?id=${COLLECTION.history_id}`);
        expect(link.text()).toContain(COLLECTION.name!);
    });

    it("badges deleted and purged datasets", () => {
        const deleted = mountCell({ ...DATASET, deleted: true });
        expect(deleted.find(".badge").text()).toBe("deleted");
        expect(deleted.findComponent(LINK_STUB).props("linkClass")).toBe("comparison-item-deleted");
        expect(
            mountCell({ ...DATASET, deleted: true, purged: true })
                .find(".badge")
                .text(),
        ).toBe("purged");
    });

    it("renders a dash for an absent cell", () => {
        expect(mountCell(undefined).text()).toBe("—");
    });
});

describe("ComparisonCell metadata", () => {
    const withLines: DatasetCell = { ...DATASET, metadata: { data_lines: 62703, columns: [1, 2] } };

    it("shows the requested element", () => {
        expect(mountCell(withLines, "meta:data_lines", ["data_lines"]).find("code").text()).toBe("62703");
    });

    it("says not set when the server filled nothing", () => {
        expect(mountCell({ ...DATASET, metadata: {} }, "meta:data_lines", ["data_lines"]).text()).toBe("not set");
    });

    it("waits while the element is being fetched", () => {
        expect(mountCell(withLines, "meta:data_lines", [], true).text()).toBe("loading…");
    });

    it("shows a dash, not loading, when the element was not fetched and nothing is loading", () => {
        const wrapper = mountCell(withLines, "meta:data_lines", [], false);
        expect(wrapper.text()).toBe("—");
        expect(wrapper.find(".comparison-metadata-unloaded").attributes("title")).toBe("Not loaded");
    });

    it("explains that collections have no dataset metadata", () => {
        expect(mountCell(COLLECTION, "meta:data_lines", ["data_lines"]).text()).toBe("list · 3");
    });
});

describe("ComparisonCell values", () => {
    function value(v: unknown, extra: Partial<Cell> = {}): Cell {
        return { type: "value", value: v, source: "parameter", ...extra } as Cell;
    }

    it.each([
        [42, "42", "comparison-value-number"],
        [true, "true", "comparison-value-boolean"],
        ["exon", "exon", "comparison-value-string"],
        [null, "null", "comparison-value-null"],
    ])("renders %s inline", (v, text, cls) => {
        const code = mountCell(value(v), "value").find("code");
        expect(code.text()).toBe(text);
        expect(code.classes()).toContain(cls);
    });

    it("pretty-prints JSON", () => {
        const pre = mountCell(value({ genes: [1, 2] }), "value").find("pre");
        expect(pre.text()).toBe('{\n  "genes": [\n    1,\n    2\n  ]\n}');
    });

    it("links an inlined expression value to its dataset in link mode", () => {
        const cell = value(18204, { source: "expression_json", dataset_id: "ds1" } as Partial<Cell>);
        expect(mountCell(cell, "value").findComponent(LINK_STUB).exists()).toBe(false);
        const link = mountCell(cell, "link").findComponent(LINK_STUB);
        expect(link.props("itemId")).toBe("ds1");
        expect(link.text()).toBe("18204");
    });
});

describe("ComparisonCell missing", () => {
    it.each([
        ["not_in_version", "not in v2"],
        ["not_run_yet", "not run yet"],
        ["skipped", "skipped"],
        ["no_output", "no output"],
        ["inaccessible", "no access"],
    ] as [MissingCell["reason"], string][])("%s reads %s with a reason title", (reason, text) => {
        const wrapper = mountCell({ type: "missing", reason });
        expect(wrapper.find(".badge").text()).toBe(text);
        expect(wrapper.find(".comparison-missing").attributes("title")).toBeTruthy();
        expect(wrapper.findComponent(LINK_STUB).exists()).toBe(false);
    });

    it("never reveals anything about an inaccessible item", () => {
        const wrapper = mountCell({ type: "missing", reason: "inaccessible" }, "meta:data_lines", ["data_lines"]);
        expect(wrapper.find(".comparison-missing-inaccessible").exists()).toBe(true);
        expect(wrapper.text()).toBe("—no access");
        expect(wrapper.findComponent(LINK_STUB).exists()).toBe(false);
        expect(wrapper.find("code").exists()).toBe(false);
    });
});
