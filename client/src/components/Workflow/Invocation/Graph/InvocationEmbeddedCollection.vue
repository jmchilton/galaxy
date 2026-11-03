<script setup lang="ts">
import { computed, ref, watch } from "vue";

import type { DCESummary, HDCASummary } from "@/api";
import { fetchCollectionElements, fetchCollectionSummary } from "@/api/datasetCollections";
import { errorMessageAsString } from "@/utils/simple-error";

import CollectionDescription from "@/components/History/Content/Collection/CollectionDescription.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

/** More than a card's height shows; the card is clipped */
const SHOWN_ELEMENTS = 2;

const props = defineProps<{
    collectionId: string;
}>();

const summary = ref<HDCASummary>();
const elements = ref<DCESummary[]>([]);
const errorText = ref("");

/** A card shows the collection's summary and its first few elements, so it loads only those, not every element */
async function load(collectionId: string) {
    const isCurrent = () => collectionId === props.collectionId;
    try {
        const loadedSummary = await fetchCollectionSummary({ hdca_id: collectionId });
        const loadedElements = await fetchCollectionElements({
            hdcaId: collectionId,
            collectionId: loadedSummary.collection_id,
            limit: SHOWN_ELEMENTS,
        });
        if (isCurrent()) {
            summary.value = loadedSummary;
            elements.value = loadedElements;
            errorText.value = "";
        }
    } catch (e) {
        if (isCurrent()) {
            errorText.value = errorMessageAsString(e);
        }
    }
}

watch(() => props.collectionId, load, { immediate: true });

const moreCount = computed(() => (summary.value?.element_count ?? 0) - elements.value.length);
</script>

<template>
    <div class="invocation-embedded-collection" data-description="invocation embedded collection">
        <div v-if="errorText" class="text-danger">Failed to load the collection: {{ errorText }}</div>
        <LoadingSpan v-else-if="!summary" message="Loading collection" />
        <template v-else>
            <div class="font-weight-bold text-truncate">{{ summary.name }}</div>
            <CollectionDescription :hdca="summary" />
            <ul class="list-unstyled mb-0">
                <li
                    v-for="element in elements"
                    :key="element.id"
                    class="text-truncate"
                    data-description="invocation embedded collection element">
                    {{ element.element_identifier }}
                </li>
                <li v-if="moreCount > 0" class="text-muted">and {{ moreCount }} more</li>
            </ul>
        </template>
    </div>
</template>

<style scoped lang="scss">
.invocation-embedded-collection {
    padding: 0.25rem 0.5rem;

    :deep(.description) {
        font-size: inherit;
    }
}
</style>
