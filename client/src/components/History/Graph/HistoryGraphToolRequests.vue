<script setup lang="ts">
import { BAlert, BListGroup, BListGroupItem } from "bootstrap-vue";
import { ref } from "vue";

import type { GraphNode } from "@/components/Graph/types";

import HistoryGraphNodeDetails from "./HistoryGraphNodeDetails.vue";

interface Props {
    /** Tool-request graph nodes to list. */
    nodes: GraphNode[];
}

defineProps<Props>();

const selected = ref<GraphNode | null>(null);

function select(node: GraphNode) {
    selected.value = selected.value?.id === node.id ? null : node;
}
</script>

<template>
    <div class="history-graph-tool-requests p-2">
        <BAlert v-if="nodes.length === 0" show variant="info" class="mb-0">
            No tool executions found in this history graph.
        </BAlert>
        <template v-else>
            <BListGroup class="mb-2">
                <BListGroupItem
                    v-for="node in nodes"
                    :key="node.id"
                    button
                    :active="selected?.id === node.id"
                    @click="select(node)">
                    {{ node.label }}
                </BListGroupItem>
            </BListGroup>
            <HistoryGraphNodeDetails :node="selected" empty-text="Select a tool execution above to view its details." />
        </template>
    </div>
</template>
