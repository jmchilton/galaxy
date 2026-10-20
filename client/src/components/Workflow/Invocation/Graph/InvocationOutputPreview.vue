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
}
</style>
