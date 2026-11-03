<script setup lang="ts">
import { computed, watch } from "vue";

import { NON_TERMINAL_STATES } from "@/api/jobs";
import type { GraphStep, GraphStepState, InvocationOutputItem } from "@/composables/useInvocationGraph";
import { useDatasetStore } from "@/stores/datasetStore";
import { useDatasetTextContentStore } from "@/stores/datasetTextContentStore";

import CollectionDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetCollection/CollectionDisplay.vue";
import HistoryDatasetDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetDisplay.vue";

const props = defineProps<{
    item: InvocationOutputItem;
    /** The step that produces the item; the preview reloads when its state changes */
    step: GraphStep;
}>();

/** The step's jobs haven't finished, so the item has no content to show yet. A subworkflow step's state is its
 * invocation step's, which stays `scheduled` (shown as `queued`) after its outputs are done. */
const notReady = computed(() => props.step.type !== "subworkflow" && NON_TERMINAL_STATES.includes(props.step.state));

const datasetStore = useDatasetStore();
const datasetTextContentStore = useDatasetTextContentStore();

// The dataset stores cache by id, so a preview loaded while its job ran would keep showing that. Nothing is shown
// while the step isn't ready, so reload only once it is.
watch(
    () => [props.item, props.step.state] as const,
    ([item, state]) => {
        if (item.src !== "hda") {
            return;
        }
        const stale = loadedUnderState.has(item.id) && loadedUnderState.get(item.id) !== state;
        loadedUnderState.set(item.id, state);
        if (stale && !notReady.value) {
            datasetStore.fetchDataset({ id: item.id });
            datasetTextContentStore.fetchItemById({ id: item.id });
        }
    },
    { immediate: true },
);
</script>

<script lang="ts">
/** The producing step's state when each dataset preview last loaded, by dataset id. Previews unmount between
 * hovers whose step changed state meanwhile, so this outlives them. */
const loadedUnderState = new Map<string, GraphStepState>();
</script>

<template>
    <div class="invocation-output-preview" data-description="invocation output preview">
        <div v-if="notReady" class="text-muted">This output isn't ready yet: the step is {{ props.step.state }}.</div>
        <HistoryDatasetDisplay v-else-if="props.item.src === 'hda'" :dataset-id="props.item.id" embedded />
        <!-- CollectionDisplay fetches when it mounts -->
        <CollectionDisplay v-else :key="props.step.state" :collection-id="props.item.id" />
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
