<script setup lang="ts">
import { BAlert, BCard, BCardBody, BCardHeader } from "bootstrap-vue";
import { computed } from "vue";

import type { GraphNode } from "@/components/Graph/types";

import HistoryGraphNodeBody from "./HistoryGraphNodeBody.vue";

interface Props {
    /** The selected graph node, or null when nothing is selected. */
    node: GraphNode | null;
    /** Empty-state message shown when no node is selected. */
    emptyText?: string;
}

const props = withDefaults(defineProps<Props>(), {
    emptyText: "Click on a node in the graph above to view its details.",
});

const typeLabel = computed(() => (props.node?.data?.typeLabel as string) ?? "Item");
</script>

<template>
    <BAlert v-if="!node" show variant="info" class="mb-0">{{ emptyText }}</BAlert>
    <BCard v-else class="history-graph-node-card h-100 d-flex flex-column" no-body>
        <BCardHeader class="d-flex align-items-center flex-gapx-1">
            <span class="font-weight-bold">{{ typeLabel }}</span>
            <span class="text-truncate text-muted">{{ node.label }}</span>
        </BCardHeader>
        <BCardBody body-class="p-2 d-flex flex-column flex-grow-1 graph-node-card-body">
            <HistoryGraphNodeBody :node="node" />
        </BCardBody>
    </BCard>
</template>

<style lang="scss" scoped>
// Pin the BCard header *and* the GTabs nav row by pushing the scroll boundary
// all the way to GTabs's `.tab-content`. Each flex level needs `min-height: 0`
// so children can shrink below their content size — without it the scroll
// never kicks in and the parent overflows instead.
:deep(.graph-node-card-body) {
    min-height: 0;
}
:deep(.graph-node-card-body > *) {
    flex: 1 1 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
}
:deep(.tabs) {
    flex: 1 1 0;
    min-height: 0;
    display: flex;
    flex-direction: column;
}
:deep(.tab-content) {
    flex: 1 1 0;
    min-height: 0;
    overflow-y: auto;
    overflow-x: hidden;
}
</style>
