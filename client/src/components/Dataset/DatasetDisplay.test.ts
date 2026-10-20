import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import type { HDADetailed, HistoryContentItemBase } from "@/api";
import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useDatasetStore } from "@/stores/datasetStore";

import DatasetDisplay from "./DatasetDisplay.vue";

// Stubbed by module: as a <script setup> import it can't be stubbed by name, and the real view fetches content.
vi.mock("@/components/Dataset/Tabular/TabularChunkedView.vue", () => ({
    default: {
        name: "TabularChunkedView",
        props: ["options"],
        render: (h: (tag: string, data: object) => unknown) => h("div", { class: "tabular-chunked-view" }),
    },
}));

const DATASET_ID = "dataset_id";

const localVue = getLocalVue();
const { server, http } = useServerMock();

const okDataset = {
    id: DATASET_ID,
    name: "Test Dataset",
    state: "ok",
    deleted: false,
    file_ext: "txt",
    file_size: 100,
    peek: "Needs a peek",
    update_time: "2026-01-01T00:00:00",
} as unknown as HDADetailed;

/** A promise that settles when the returned ``release`` is called, to hold a mocked response open. */
function hold() {
    let release: () => void = () => {};
    const released = new Promise<void>((resolve) => {
        release = resolve;
    });
    return { released, release };
}

function usePreviewHeaders(headers: Record<string, string> = {}) {
    server.use(
        http.untyped.head("/datasets/:dataset_id/display/", () => {
            return new HttpResponse(null, { headers });
        }),
    );
}

/** Serve ``dataset`` from the dataset details API once ``release`` is called. */
function holdDatasetFetch(dataset: HDADetailed) {
    const { released, release } = hold();
    server.use(
        http.untyped.get("/api/datasets/:dataset_id", async () => {
            await released;
            return HttpResponse.json(dataset);
        }),
    );
    return release;
}

/** Store an item the way the history watcher does; summaries lack ``peek`` and trigger a detailed refetch. */
function storeHistoryItem(item: object) {
    useDatasetStore().saveDatasets([{ ...item, history_content_type: "dataset" } as unknown as HistoryContentItemBase]);
}

async function mountDatasetDisplay(dataset: HDADetailed | null = okDataset) {
    const storedDatasets = dataset ? { [DATASET_ID]: dataset } : {};
    const pinia = createTestingPinia({
        createSpy: vi.fn,
        stubActions: false,
        initialState: { datasetStore: { storedDatasets } },
    });
    setActivePinia(pinia);

    const wrapper = mount(DatasetDisplay as object, {
        propsData: { datasetId: DATASET_ID, isBinary: false },
        localVue,
        pinia,
        stubs: { FontAwesomeIcon: true },
    });
    await flushPromises();
    return wrapper;
}

describe("DatasetDisplay", () => {
    it("shows the dataset preview in a frame", async () => {
        usePreviewHeaders();
        const wrapper = await mountDatasetDisplay();
        expect(wrapper.find(".dataset-display").exists()).toBe(true);
        expect(wrapper.find("iframe").attributes("src")).toBe(`/datasets/${DATASET_ID}/display/?preview=True`);
        expect(wrapper.find(".tabular-chunked-view").exists()).toBe(false);
    });

    it("shows chunked datasets in the tabular view", async () => {
        usePreviewHeaders({ "x-content-chunked": "true" });
        const wrapper = await mountDatasetDisplay();
        expect(wrapper.find(".tabular-chunked-view").exists()).toBe(true);
        expect(wrapper.find("iframe").exists()).toBe(false);
    });

    it("warns when the preview is truncated", async () => {
        usePreviewHeaders({ "x-content-truncated": "1024" });
        const wrapper = await mountDatasetDisplay();
        expect(wrapper.find(".warningmessagelarge").text()).toContain("only the first");
    });

    it("waits for pending datasets", async () => {
        usePreviewHeaders();
        const wrapper = await mountDatasetDisplay({ ...okDataset, state: "running" });
        expect(wrapper.text()).toContain("Waiting for dataset to become available.");
        expect(wrapper.find(".dataset-display").exists()).toBe(false);
    });

    it("reports unavailable datasets", async () => {
        usePreviewHeaders();
        const wrapper = await mountDatasetDisplay({ ...okDataset, state: "error" });
        expect(wrapper.text()).toContain("Dataset is unavailable.");
        expect(wrapper.find(".dataset-display").exists()).toBe(false);
    });

    it("shows a loading message until the dataset is stored", async () => {
        usePreviewHeaders();
        const releaseFetch = holdDatasetFetch(okDataset);
        const wrapper = await mountDatasetDisplay(null);
        expect(wrapper.text()).toContain("Loading dataset content");

        releaseFetch();
        await flushPromises();
        expect(wrapper.find(".dataset-display").exists()).toBe(true);
        expect(useDatasetStore().getDataset(DATASET_ID)?.name).toBe("Test Dataset");
    });

    it("keeps the preview frame while a history update refetches the dataset", async () => {
        usePreviewHeaders();
        const wrapper = await mountDatasetDisplay();
        const frame = wrapper.find("iframe").element;

        const releaseFetch = holdDatasetFetch({ ...okDataset, name: "Renamed Dataset" });
        storeHistoryItem({ id: DATASET_ID, name: "Renamed Dataset", state: "ok" });
        await flushPromises();
        expect(useDatasetStore().isLoadingDataset(DATASET_ID)).toBe(true);
        expect(wrapper.text()).not.toContain("Loading dataset content");
        expect(wrapper.find("iframe").element).toBe(frame);

        releaseFetch();
        await flushPromises();
        expect(wrapper.find("iframe").element).toBe(frame);
    });

    it("rechecks the preview once a pending dataset finishes", async () => {
        usePreviewHeaders();
        const wrapper = await mountDatasetDisplay({ ...okDataset, state: "running" });
        expect(wrapper.text()).toContain("Waiting for dataset to become available.");

        // The history watcher reports the finished dataset as a summary, then the store refetches its details.
        usePreviewHeaders({ "x-content-chunked": "true" });
        const finished = { ...okDataset, update_time: "2026-01-01T00:05:00" };
        const releaseFetch = holdDatasetFetch(finished);
        storeHistoryItem({ id: DATASET_ID, name: okDataset.name, state: "ok", update_time: finished.update_time });
        await flushPromises();
        expect(useDatasetStore().isLoadingDataset(DATASET_ID)).toBe(true);
        expect(wrapper.text()).toContain("Waiting for dataset to become available.");

        releaseFetch();
        await flushPromises();
        expect(wrapper.find(".tabular-chunked-view").exists()).toBe(true);
        expect(wrapper.find("iframe").exists()).toBe(false);
    });

    it("ignores a preview check that finishes after a newer one", async () => {
        const { released: firstReleased, release: releaseFirst } = hold();
        let checks = 0;
        server.use(
            http.untyped.head("/datasets/:dataset_id/display/", async () => {
                checks += 1;
                if (checks === 1) {
                    await firstReleased;
                    return new HttpResponse(null);
                }
                return new HttpResponse(null, { headers: { "x-content-chunked": "true" } });
            }),
        );
        const wrapper = await mountDatasetDisplay();

        storeHistoryItem({ ...okDataset, update_time: "2026-01-01T00:05:00" });
        await flushPromises();
        expect(wrapper.find(".tabular-chunked-view").exists()).toBe(true);

        releaseFirst();
        await flushPromises();
        expect(checks).toBe(2);
        expect(wrapper.find(".tabular-chunked-view").exists()).toBe(true);
    });
});
