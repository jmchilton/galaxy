import { type MaybeRefOrGetter, toValue } from "@vueuse/core";
import { computed, shallowRef, watch } from "vue";

import { hasDetails, type HDADetailed, isInaccessible } from "@/api";
import { useDatasetStore } from "@/stores/datasetStore";

/** Whether a stored dataset is fully loaded, i.e. not a summary from the history watcher. */
export function isSettledDataset(dataset?: HDADetailed | null): dataset is HDADetailed {
    return Boolean(dataset && (hasDetails(dataset) || isInaccessible(dataset)));
}

/**
 * The last fully loaded version of a dataset, held while the dataset store refetches it.
 *
 * The history watcher stores summaries over detailed datasets, which makes the store refetch them.
 * Gating a view on the store's loading state blanks it on every such refetch; gating on this value
 * only blocks until the dataset first loads, and again after `datasetId` changes.
 *
 * @param datasetId The id of the dataset.
 * @param extraLoading Other loading to wait for before taking a new version, e.g. datatype details.
 * It never clears a held dataset. The first check runs when this is called, so start that loading first.
 */
export function useSettledDataset(
    datasetId: MaybeRefOrGetter<string>,
    extraLoading: MaybeRefOrGetter<boolean> = false,
) {
    const datasetStore = useDatasetStore();
    const settled = shallowRef<{ id: string; dataset: HDADetailed }>();

    watch(
        () => {
            const id = toValue(datasetId);
            const dataset = datasetStore.getDataset(id);
            const isLoading = datasetStore.isLoadingDataset(id) || toValue(extraLoading);
            return isSettledDataset(dataset) && !isLoading ? { id, dataset } : undefined;
        },
        (ready) => {
            if (ready) {
                settled.value = ready;
            }
        },
        { immediate: true },
    );

    return computed(() => (settled.value?.id === toValue(datasetId) ? settled.value.dataset : null));
}
