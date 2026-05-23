<script setup lang="ts">
import { BAlert, BBadge } from "bootstrap-vue";
import { ref } from "vue";

import type { GraphNode } from "@/components/Graph/types";

import FormCard from "@/components/Form/FormCard.vue";
import HistoryGraphNodeBody from "./HistoryGraphNodeBody.vue";

interface Props {
    /** Tool-execution graph nodes to list, in display order. */
    nodes: GraphNode[];
}

defineProps<Props>();

// Independent per-row expanded state — multiple sections can be open at once,
// mirroring the workflow invocation graph's collapsible step cards.
const expanded = ref(new Set<string>());

function isExpanded(id: string): boolean {
    return expanded.value.has(id);
}

function setExpanded(id: string, value: boolean) {
    // Reassign so Vue picks up the change (Set mutations aren't reactive in Vue 2.7).
    const next = new Set(expanded.value);
    if (value) {
        next.add(id);
    } else {
        next.delete(id);
    }
    expanded.value = next;
}
</script>

<template>
    <div class="history-graph-tool-executions p-2">
        <BAlert v-if="nodes.length === 0" show variant="info" class="mb-0">
            No tool executions found in this history graph.
        </BAlert>
        <template v-else>
            <FormCard
                v-for="(node, index) in nodes"
                :key="node.id"
                class="mb-2"
                :title="`${index + 1}. ${node.label}`"
                :icon="node.icon"
                collapsible
                :expanded="isExpanded(node.id)"
                @update:expanded="setExpanded(node.id, $event)">
                <template v-if="node.data?.state" v-slot:operations>
                    <BBadge variant="secondary" class="text-uppercase">{{ node.data.state }}</BBadge>
                </template>
                <template v-slot:body>
                    <HistoryGraphNodeBody class="p-2" :node="node" />
                </template>
            </FormCard>
        </template>
    </div>
</template>
