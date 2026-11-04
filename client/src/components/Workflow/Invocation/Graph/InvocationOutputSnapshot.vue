<script setup lang="ts">
import type { GraphStep, InvocationOutputItem } from "@/composables/useInvocationGraph";

import InvocationOutputPreview from "./InvocationOutputPreview.vue";

defineProps<{
    item: InvocationOutputItem;
    /** The step that produces the item; the snapshot follows its state */
    step: GraphStep;
}>();
</script>

<template>
    <!-- a static snapshot, drawn on the graph as part of it: clicks select what's beneath, drags and zooms move the
         graph, nothing takes focus, and the step details hold the interactive output. A collection's full preview
         loads every element, more than a snapshot can show, so it's summarized. -->
    <div class="invocation-output-snapshot" inert>
        <InvocationOutputPreview :item="item" :step="step" summarize-collection />
    </div>
</template>

<style scoped lang="scss">
.invocation-output-snapshot {
    overflow: hidden;
    pointer-events: none;
    font-size: 0.75rem;
    // images fill the snapshot, less the preview's padding and border, at any root font size
    container-type: size;
    --invocation-output-image-height: calc(100cqh - 1rem - 2px);

    // clipped to the snapshot, not scrolled: a static snapshot can't be scrolled
    :deep(.invocation-output-preview) {
        overflow: hidden;
    }

    :deep(.image-wrapper) {
        display: block;
    }

    :deep(img) {
        width: 100%;
        height: var(--invocation-output-image-height);
    }

    // a table's first rows; it can't be sorted or paged on a static snapshot, so drop those controls and tighten
    // the rows
    :deep(.pagination) {
        display: none;
    }

    :deep(.g-table-container .g-table) {
        margin-bottom: 0;
        line-height: 1.3;

        thead th,
        tbody td {
            padding: 0.125rem 0.375rem;
        }

        thead th svg {
            display: none;
        }
    }
}
</style>
