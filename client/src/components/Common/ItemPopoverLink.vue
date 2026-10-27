<script setup lang="ts">
import { computed, ref } from "vue";

import type { HDCASummary } from "@/api";
import { fetchCollectionSummary } from "@/api/datasetCollections";
import { useUid } from "@/composables/utils/uid";
import { useDatasetStore } from "@/stores/datasetStore";
import localize from "@/utils/localization";
import { errorMessageAsString } from "@/utils/simple-error";

import GPopover from "@/components/BaseComponents/GPopover.vue";
import DatasetInformation from "@/components/DatasetInformation/DatasetInformation.vue";
import CollectionDescription from "@/components/History/Content/Collection/CollectionDescription.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const props = withDefaults(
    defineProps<{
        itemId: string;
        itemSrc?: "hda" | "hdca";
        /** Route for the link; datasets default to their details page. */
        to?: string;
        linkClass?: string;
    }>(),
    { itemSrc: "hda", to: undefined, linkClass: undefined },
);

const datasetStore = useDatasetStore();

// Page-unique, so the same item can appear in many rows.
const targetId = useUid("item-popover-");

const isCollection = computed(() => props.itemSrc === "hdca");
const route = computed(() => props.to ?? (isCollection.value ? undefined : `/datasets/${props.itemId}/details`));

const popoverShown = ref(false);

// The getter fetches when read, and refetches after a retry backoff; use it only while the popover is shown.
const dataset = computed(() => {
    if (isCollection.value) {
        return undefined;
    }
    return popoverShown.value ? datasetStore.getDataset(props.itemId) : datasetStore.storedDatasets[props.itemId];
});

// Collections use the light summary view, not the store's element-loading detail fetch.
const collection = ref<HDCASummary>();
const collectionLoading = ref(false);
const collectionError = ref<string>();

const loading = computed(() =>
    isCollection.value ? collectionLoading.value : datasetStore.isLoadingDataset(props.itemId),
);
const loadError = computed(() =>
    isCollection.value ? collectionError.value : datasetStore.getDatasetError(props.itemId)?.message,
);
const details = computed(() => (isCollection.value ? collection.value : dataset.value));
// The trigger may read as an encoded id, so name the dialog by the item.
const popoverName = computed(
    () => details.value?.name || localize(isCollection.value ? "Collection details" : "Dataset details"),
);

async function ensureDetails() {
    if (details.value || loading.value) {
        return;
    }
    if (!isCollection.value) {
        await datasetStore.fetchDataset({ id: props.itemId });
        return;
    }
    collectionLoading.value = true;
    collectionError.value = undefined;
    try {
        collection.value = await fetchCollectionSummary({ hdca_id: props.itemId });
    } catch (e) {
        collectionError.value = errorMessageAsString(e);
    } finally {
        collectionLoading.value = false;
    }
}
</script>

<template>
    <span class="item-popover-link">
        <router-link
            v-if="route"
            :id="targetId"
            :class="linkClass"
            :to="route"
            @mouseenter="ensureDetails"
            @focus="ensureDetails">
            <slot>{{ itemId }}</slot>
        </router-link>
        <span
            v-else
            :id="targetId"
            :class="linkClass"
            role="button"
            tabindex="0"
            @mouseenter="ensureDetails"
            @focus="ensureDetails">
            <slot>{{ itemId }}</slot>
        </span>

        <GPopover
            interactive
            :aria-label="popoverName"
            :target="targetId"
            triggers="hover focus"
            boundary="window"
            placement="right"
            @shown="popoverShown = true"
            @hidden="popoverShown = false">
            <div class="item-details-popover" :class="{ 'dataset-details-popover': !isCollection }">
                <div v-if="loading">
                    <LoadingSpan
                        :message="localize(isCollection ? 'Loading collection details' : 'Loading dataset details')" />
                </div>
                <div v-else-if="loadError" class="text-danger">
                    {{ loadError }}
                </div>
                <div v-else-if="collection && isCollection">
                    <div class="font-weight-bold">{{ collection.name }}</div>
                    <CollectionDescription :hdca="collection" />
                </div>
                <div v-else-if="dataset">
                    <DatasetInformation :dataset="dataset" />
                </div>
            </div>
        </GPopover>
    </span>
</template>

<style scoped>
.item-details-popover {
    max-width: 420px;
}
</style>
