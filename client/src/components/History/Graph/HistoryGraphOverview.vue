<script setup lang="ts">
import { BAlert } from "bootstrap-vue";
import { ref } from "vue";

import type { GraphEdge, GraphNode } from "@/components/Graph/types";

import { historyNodeColor } from "./historyNodeColor";

import HistoryGraphNodeDetails from "./HistoryGraphNodeDetails.vue";
import GraphView from "@/components/Graph/GraphView.vue";

interface Props {
    nodes: GraphNode[];
    edges: GraphEdge[];
    focusNodeId?: string | null;
    truncated?: boolean;
}

withDefaults(defineProps<Props>(), {
    focusNodeId: null,
    truncated: false,
});

// Selected graph node — its details render in the card below the graph.
const selectedNode = ref<GraphNode | null>(null);

function onNodeSelected(node: GraphNode | null) {
    selectedNode.value = node;
}
</script>

<template>
    <div class="history-graph-overview">
        <div class="graph-pane rounded border">
            <GraphView
                :nodes="nodes"
                :edges="edges"
                :focus-node-id="focusNodeId"
                :node-color="historyNodeColor"
                center-on-select
                show-scroll-overlays
                @nodeSelected="onNodeSelected" />
        </div>
        <BAlert v-if="truncated" variant="warning" show class="mt-2 mb-0 py-1 text-center flex-shrink-0">
            Showing a partial graph. Not all connections are visible.
        </BAlert>
        <HistoryGraphNodeDetails class="mt-2 flex-shrink-0" :node="selectedNode" />
    </div>
</template>

<style lang="scss" scoped>
@import "@/style/scss/theme/blue.scss";

// Fill the tab container as a flex column so the graph pane absorbs exactly
// the space left by the details card — no fixed height that overflows slightly.
.history-graph-overview {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-height: 0;
}

.graph-pane {
    display: flex;
    flex: 1;
    min-height: 400px;
}

/* Tool request nodes use the primary header colour (no dataset state). */
:deep(.node-tool-request) .graph-node-header {
    background: $brand-primary;
    color: $white;
}

/* Dataset/collection node headers use state-driven colouring via data-state. */
:deep(.node-dataset) .graph-node-header,
:deep(.node-collection) .graph-node-header {
    color: $text-color;
}
</style>
