import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ComparisonQuery, ComparisonRow, ComparisonTable } from "@/api/comparisons";

import STEP_RUNS from "./test-data/step_runs.json";

import ComparisonRowDetail from "./ComparisonRowDetail.vue";

const TABLE = STEP_RUNS as unknown as ComparisonTable;
const JOB_TABS_STUB = { name: "JobDetailsTabs", props: ["jobId"], template: "<div />" };
const ITEM_STUB = { name: "GenericHistoryItem", props: ["itemId", "itemSrc"], template: "<div />" };

function mountDetail(row: ComparisonRow, query: ComparisonQuery = TABLE.query) {
    const localVue = getLocalVue();
    return mount(ComparisonRowDetail as object, {
        props: { row, columns: TABLE.columns, query },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, JobDetailsTabs: JOB_TABS_STUB, GenericHistoryItem: ITEM_STUB },
        },
    });
}

describe("ComparisonRowDetail", () => {
    it("shows the output history items and the step job", () => {
        const row = TABLE.rows[1]!;
        const wrapper = mountDetail(row);
        const items = wrapper.findAllComponents(ITEM_STUB);
        expect(items.map((i) => [i.props("itemId"), i.props("itemSrc")])).toEqual([
            [(row.cells["output:out_file1"] as { id: string }).id, "hda"],
        ]);
        expect(wrapper.findComponent(JOB_TABS_STUB).props("jobId")).toBe(row.step_job!.id);
    });

    it("uses a mapped step's first job", () => {
        const wrapper = mountDetail(TABLE.rows[4]!);
        expect(wrapper.findComponent(JOB_TABS_STUB).props("jobId")).toBe("cb227cec8ca83994");
        expect(wrapper.text()).toContain("Job 1 of 3");
        expect(wrapper.findComponent(ITEM_STUB).props("itemSrc")).toBe("hdca");
    });

    it("explains a step that has not run yet", () => {
        const wrapper = mountDetail(TABLE.rows[0]!);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("no job for this step yet");
        expect(wrapper.text()).toContain("No outputs.");
    });

    it("has no single job for a workflow-outputs row", () => {
        const query = { kind: "output_runs", workflow_id: "w" } as ComparisonQuery;
        const row = { ...TABLE.rows[1]!, step_job: null };
        const wrapper = mountDetail(row, query);
        expect(wrapper.findComponent(JOB_TABS_STUB).exists()).toBe(false);
        expect(wrapper.text()).toContain("no single job");
    });
});
