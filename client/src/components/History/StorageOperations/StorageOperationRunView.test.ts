import { currentPagerPage, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it, vi } from "vitest";
import { computed, ref } from "vue";

import { useServerMock } from "@/api/client/__mocks__";

import StorageOperationRunView from "./StorageOperationRunView.vue";

const TOTAL_FAILED = 120;

const { server, http } = useServerMock();

vi.mock("@/composables/useStorageRunWatcher", () => ({
    useStorageRunWatcher: () => {
        const runStatus = ref({
            run: {
                run_id: "run-1",
                state: "completed",
                mode: "copy",
                target_object_store_id: "store-1",
                total_count: TOTAL_FAILED,
                succeeded_count: 0,
                failed_count: TOTAL_FAILED,
                skipped_count: 0,
                total_bytes_processed: 0,
                create_time: "2026-01-01T00:00:00",
                update_time: "2026-01-01T00:01:00",
            },
        });
        return { runStatus, isTerminal: computed(() => true), startPolling: vi.fn(), stopPolling: vi.fn() };
    },
}));

function mockRunItems() {
    const offsets: number[] = [];
    server.use(
        http.get("/api/histories/{history_id}/contents/bulk/storage/runs/{run_id}/items", ({ query, response }) => {
            offsets.push(Number(query.get("offset")));
            return response(200).json([], { headers: { total_matches: String(TOTAL_FAILED) } });
        }),
        http.get("/api/object_stores", ({ response }) => response(200).json([])),
    );
    return offsets;
}

async function mountRunView() {
    const localVue = getLocalVue();
    const wrapper = mount(StorageOperationRunView as object, {
        props: { historyId: "history-1", runId: "run-1" },
        global: {
            ...localVue,
            stubs: {
                ...localVue.stubs,
                BreadcrumbHeading: true,
                DatasetPopoverLink: true,
                FilterMenu: true,
                StorageOperationOutcomeProgress: true,
                StorageOperationRunStateBadge: true,
            },
        },
    });
    await flushPromises();
    return wrapper;
}

describe("StorageOperationRunView", () => {
    it("loads the page picked in the pager", async () => {
        const offsets = mockRunItems();
        const wrapper = await mountRunView();

        expect(pagerPages(wrapper)).toEqual(["1", "2", "3"]);
        expect(currentPagerPage(wrapper)).toBe("1");
        expect(offsets).toEqual([0]);

        await goToPage(wrapper, 3);
        await flushPromises();

        expect(currentPagerPage(wrapper)).toBe("3");
        expect(offsets).toEqual([0, 100]);
    });
});
