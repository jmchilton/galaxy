<script setup lang="ts">
import type { InvocationOutputItem } from "@/composables/useInvocationGraph";

import CollectionDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetCollection/CollectionDisplay.vue";
import HistoryDatasetDisplay from "@/components/Markdown/Sections/Elements/HistoryDatasetDisplay.vue";

const props = defineProps<{
    item: InvocationOutputItem;
}>();
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
