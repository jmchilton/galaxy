<script setup lang="ts">
import { watch } from "vue";

import type { InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useDatasetStore } from "@/stores/datasetStore";
import { useDatasetTextContentStore } from "@/stores/datasetTextContentStore";

import CollectionDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetCollection/CollectionDisplay.vue";
import HistoryDatasetDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetDisplay.vue";

const props = defineProps<{
    item: InvocationOutputItem;
    /** State of the step that produces the item; the preview reloads when it changes */
    stepState?: string;
}>();

const datasetStore = useDatasetStore();
const datasetTextContentStore = useDatasetTextContentStore();

// the dataset stores cache by id, so a preview loaded while the job ran would stay empty
watch(
    () => props.stepState,
    () => {
        if (props.item.src === "hda") {
            datasetStore.fetchDataset({ id: props.item.id });
            datasetTextContentStore.fetchItemById({ id: props.item.id });
        }
    },
);
</script>

<template>
    <div class="invocation-output-preview" data-description="invocation output preview">
        <HistoryDatasetDisplay v-if="props.item.src === 'hda'" :dataset-id="props.item.id" embedded />
        <CollectionDisplay v-else :collection-id="props.item.id" />
    </div>
</template>

<style scoped lang="scss">
.invocation-output-preview {
    width: 100%;
    max-height: 100%;
    overflow: auto;

    // previews are small: drop the Markdown card's padding and fixed text height
    :deep(.card-body) {
        padding: 0.5rem;
    }

    :deep(.embedded-dataset) {
        height: auto;
        max-height: 10rem;
        margin-bottom: 0;
    }

    :deep(img) {
        display: block;
        max-width: 100%;
        max-height: var(--invocation-output-image-height, 20rem);
        margin: 0 auto;
        object-fit: contain;
    }
}
</style>

<style lang="scss">
.invocation-output-popover {
    max-width: 40rem;
    width: 40rem;

    .popover-body {
        max-height: 25rem;
        overflow: auto;
    }
}
</style>
