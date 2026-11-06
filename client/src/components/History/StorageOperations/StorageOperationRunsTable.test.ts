import { currentPagerPage, emittedArg, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import StorageOperationRunsTable from "./StorageOperationRunsTable.vue";

vi.mock("@/stores/objectStoreStore", () => ({
    useObjectStoreStore: () => ({ getObjectStoreNameById: () => null }),
}));

function makeRows(count: number) {
    return Array.from({ length: count }, (_, index) => ({
        run_id: `run-${index + 1}`,
        historyId: "history-1",
        runUrl: `/histories/history-1/storage/runs/run-${index + 1}`,
        state: "completed",
        mode: "copy",
        target_object_store_id: "store-1",
        total_count: 1,
        succeeded_count: 1,
        failed_count: 0,
        skipped_count: 0,
        total_bytes_processed: 10,
        create_time: "2026-01-01T00:00:00",
        update_time: "2026-01-01T00:01:00",
        progressPercent: 100,
    }));
}

function mountTable(rowCount: number, currentPage = 1) {
    const localVue = getLocalVue();
    return mount(StorageOperationRunsTable as object, {
        props: {
            title: "Finished",
            rows: makeRows(rowCount),
            currentPage,
            perPage: 2,
            sortBy: "create_time",
            sortDesc: true,
            emptyMessage: "No runs",
        },
        global: {
            ...localVue,
            stubs: {
                ...localVue.stubs,
                StorageOperationOutcomeProgress: true,
                StorageOperationRunStateBadge: true,
                UtcDate: true,
            },
        },
    });
}

describe("StorageOperationRunsTable", () => {
    it("shows the page the parent passes in", () => {
        const wrapper = mountTable(5, 2);

        expect(pagerPages(wrapper)).toEqual(["1", "2", "3"]);
        expect(currentPagerPage(wrapper)).toBe("2");
    });

    it("emits page-change with the clicked page", async () => {
        const wrapper = mountTable(5);

        await goToPage(wrapper, 3);

        expect(emittedArg(wrapper, "page-change")).toBe(3);
    });

    it("shows no pager when every row fits on one page", () => {
        const wrapper = mountTable(2);

        expect(pagerPages(wrapper)).toEqual([]);
    });
});
