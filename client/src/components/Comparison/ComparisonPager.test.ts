import { shallowMount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import ComparisonPager from "./ComparisonPager.vue";

describe("ComparisonPager", () => {
    it.each([
        [{}, "newest first"],
        [{ sortBy: "create_time", sortDesc: false }, "oldest first"],
        [{ sortBy: "update_time", sortDesc: true }, "recently updated first"],
        [{ sortBy: "update_time", sortDesc: false }, "least recently updated first"],
    ])("summarises the page in its sort order %j", (sort, order) => {
        const wrapper = shallowMount(ComparisonPager as object, {
            props: { total: 60, limit: 25, offset: 0, loadedOffset: 0, rowCount: 25, ...sort },
        });
        expect(wrapper.find(".comparison-summary").text()).toBe(`Showing 1–25 of 60 · ${order} · your runs only`);
    });
});
