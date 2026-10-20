import { createTestingPinia } from "@pinia/testing";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EffectScope, effectScope, ref } from "vue";

import type { HDADetailed, HistoryContentItemBase } from "@/api";
import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useDatasetStore } from "@/stores/datasetStore";

import { onDatasetUpdated, useSettledDataset } from "./settledDataset";

const { server, http } = useServerMock();

const DATASET_ID = "dataset_id";
const OTHER_ID = "other_id";

function detailed(id: string, name: string) {
    return { id, name, state: "ok", file_ext: "txt", peek: "peek" } as unknown as HDADetailed;
}

function storeSummary(id: string, name: string) {
    const summary = { id, name, state: "ok", history_content_type: "dataset" };
    useDatasetStore().saveDatasets([summary as unknown as HistoryContentItemBase]);
}

function heldFetch(dataset: HDADetailed) {
    let release: () => void = () => {};
    const released = new Promise<void>((resolve) => {
        release = resolve;
    });
    server.use(
        http.untyped.get("/api/datasets/:dataset_id", async () => {
            await released;
            return HttpResponse.json(dataset);
        }),
    );
    return release;
}

let scope: EffectScope | undefined;

function useSettled(datasetId = ref(DATASET_ID), extraLoading = ref(false)) {
    scope = effectScope();
    const dataset = scope.run(() => useSettledDataset(datasetId, extraLoading))!;
    return { dataset, datasetId, extraLoading };
}

describe("useSettledDataset", () => {
    beforeEach(() => {
        setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
    });

    afterEach(() => {
        scope?.stop();
        scope = undefined;
    });

    it("is null until the dataset first loads", async () => {
        const release = heldFetch(detailed(DATASET_ID, "First"));
        const { dataset } = useSettled();
        await flushPromises();
        expect(useDatasetStore().isLoadingDataset(DATASET_ID)).toBe(true);
        expect(dataset.value).toBeNull();

        release();
        await flushPromises();
        expect(dataset.value?.name).toBe("First");
    });

    it("stays null when only a summary is stored and its details fail to load", async () => {
        server.use(
            http.untyped.get("/api/datasets/:dataset_id", () => {
                return HttpResponse.json({ err_msg: "Access denied", err_code: 403002 }, { status: 403 });
            }),
        );
        storeSummary(DATASET_ID, "Summary");
        const { dataset } = useSettled();
        await flushPromises();
        expect(useDatasetStore().getDatasetError(DATASET_ID)).not.toBeNull();
        expect(useDatasetStore().getDataset(DATASET_ID)?.name).toBe("Summary");
        expect(dataset.value).toBeNull();
    });

    it("holds the loaded dataset while a summary replaces it and refetches", async () => {
        useDatasetStore().storedDatasets = { [DATASET_ID]: detailed(DATASET_ID, "First") };
        const { dataset } = useSettled();
        expect(dataset.value?.name).toBe("First");

        const release = heldFetch(detailed(DATASET_ID, "Renamed"));
        storeSummary(DATASET_ID, "Renamed");
        await flushPromises();
        expect(useDatasetStore().isLoadingDataset(DATASET_ID)).toBe(true);
        expect(dataset.value?.name).toBe("First");
        expect(dataset.value?.peek).toBe("peek");

        release();
        await flushPromises();
        expect(dataset.value?.name).toBe("Renamed");
    });

    it("keeps the loaded dataset when a refetch fails", async () => {
        useDatasetStore().storedDatasets = { [DATASET_ID]: detailed(DATASET_ID, "First") };
        const { dataset } = useSettled();
        server.use(
            http.untyped.get("/api/datasets/:dataset_id", () => {
                return HttpResponse.json({ err_msg: "Access denied", err_code: 403002 }, { status: 403 });
            }),
        );
        storeSummary(DATASET_ID, "Renamed");
        await flushPromises();
        expect(useDatasetStore().getDatasetError(DATASET_ID)).not.toBeNull();
        expect(dataset.value?.name).toBe("First");
        expect(dataset.value?.peek).toBe("peek");
    });

    it("waits for extra loading without dropping a held dataset", async () => {
        useDatasetStore().storedDatasets = { [DATASET_ID]: detailed(DATASET_ID, "First") };
        const { dataset, extraLoading } = useSettled(ref(DATASET_ID), ref(true));
        expect(dataset.value).toBeNull();

        extraLoading.value = false;
        await flushPromises();
        expect(dataset.value?.name).toBe("First");

        extraLoading.value = true;
        await flushPromises();
        expect(dataset.value?.name).toBe("First");
    });

    it("does not show the previous dataset after switching ids", async () => {
        useDatasetStore().storedDatasets = { [DATASET_ID]: detailed(DATASET_ID, "First") };
        const { dataset, datasetId } = useSettled();
        expect(dataset.value?.name).toBe("First");

        const release = heldFetch(detailed(OTHER_ID, "Other"));
        datasetId.value = OTHER_ID;
        await flushPromises();
        expect(dataset.value).toBeNull();

        release();
        await flushPromises();
        expect(dataset.value?.name).toBe("Other");
    });
});

describe("onDatasetUpdated", () => {
    function storeDataset(id: string, updateTime: string, details = true) {
        const dataset = {
            id,
            name: "Dataset",
            state: "ok",
            update_time: updateTime,
            ...(details ? { peek: "peek" } : {}),
        };
        useDatasetStore().storedDatasets = {
            ...useDatasetStore().storedDatasets,
            [id]: dataset as unknown as HDADetailed,
        };
    }

    function watchUpdates(datasetId = ref(DATASET_ID)) {
        const callback = vi.fn();
        scope = effectScope();
        scope.run(() => onDatasetUpdated(datasetId, callback));
        return { callback, datasetId };
    }

    beforeEach(() => {
        setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
    });

    afterEach(() => {
        scope?.stop();
        scope = undefined;
    });

    it("fires when the stored dataset gets a newer update time", async () => {
        storeDataset(DATASET_ID, "2026-01-01T00:00:00");
        const { callback } = watchUpdates();
        await flushPromises();
        expect(callback).not.toHaveBeenCalled();

        storeDataset(DATASET_ID, "2026-01-01T00:00:05");
        await flushPromises();
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it("fires for a dataset first stored after it started watching", async () => {
        const { callback } = watchUpdates();
        storeDataset(DATASET_ID, "2026-01-01T00:00:00");
        await flushPromises();
        expect(callback).not.toHaveBeenCalled();

        storeDataset(DATASET_ID, "2026-01-01T00:00:05");
        await flushPromises();
        expect(callback).toHaveBeenCalledTimes(1);
    });

    it("ignores a summary that replaces the dataset with the same update time", async () => {
        storeDataset(DATASET_ID, "2026-01-01T00:00:00");
        const { callback } = watchUpdates();

        storeDataset(DATASET_ID, "2026-01-01T00:00:00", false);
        await flushPromises();
        storeDataset(DATASET_ID, "2026-01-01T00:00:00");
        await flushPromises();
        expect(callback).not.toHaveBeenCalled();
    });

    it("ignores switching to another dataset", async () => {
        storeDataset(DATASET_ID, "2026-01-01T00:00:00");
        storeDataset(OTHER_ID, "2026-01-01T00:00:05");
        const { callback, datasetId } = watchUpdates();

        datasetId.value = OTHER_ID;
        await flushPromises();
        expect(callback).not.toHaveBeenCalled();

        storeDataset(OTHER_ID, "2026-01-01T00:00:10");
        await flushPromises();
        expect(callback).toHaveBeenCalledTimes(1);
    });
});
