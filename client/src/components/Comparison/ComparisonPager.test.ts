import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { STEP_RUNS_TABLE } from "./test-utils";

import ComparisonPager from "./ComparisonPager.vue";

function mountPager(query: Record<string, unknown>, rows = STEP_RUNS_TABLE.rows) {
    const table = { ...STEP_RUNS_TABLE, rows, query: { ...STEP_RUNS_TABLE.query, ...query } };
    return shallowMount(ComparisonPager as object, { props: { table, total: 60, limit: 25, offset: 25 } });
}

describe("ComparisonPager", () => {
    it.each([
        [{ sort_by: undefined, sort_desc: undefined }, "newest first"],
        [{ sort_by: "create_time", sort_desc: false }, "oldest first"],
        [{ sort_by: "update_time", sort_desc: true }, "recently updated first"],
        [{ sort_by: "update_time", sort_desc: false }, "least recently updated first"],
    ])("summarises the loaded page in its sort order %j", (sort, order) => {
        const rowCount = STEP_RUNS_TABLE.rows.length;
        expect(
            mountPager({ offset: 25, ...sort })
                .find(".comparison-summary")
                .text(),
        ).toBe(`Showing 26–${25 + rowCount} of 60 · ${order} · your runs only`);
    });

    it("says nothing about an empty page", () => {
        expect(mountPager({}, []).find(".comparison-summary").text()).toBe("");
    });
});
