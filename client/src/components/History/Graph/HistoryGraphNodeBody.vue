<script setup lang="ts">
import { BAlert } from "bootstrap-vue";
import { computed } from "vue";

import type { GraphNode } from "@/components/Graph/types";

import GenericHistoryItem from "@/components/History/Content/GenericItem.vue";
import ToolExecutionJobs from "./ToolExecutionJobs.vue";

interface Props {
    /** The graph node to render details for. */
    node: GraphNode;
}

const props = defineProps<Props>();

const nodeSrc = computed(() => (props.node.data?.src as string) ?? null);
const itemId = computed(() => (props.node.data?.itemId as string) ?? null);

/** src GenericHistoryItem expects, for the item node kinds it can render */
const itemSrc = computed(() => {
    if (nodeSrc.value === "hda" || nodeSrc.value === "hdca") {
        return nodeSrc.value;
    }
    return null;
});
</script>

<template>
    <div v-if="itemSrc && itemId" :key="itemId">
        <GenericHistoryItem :item-id="itemId" :item-src="itemSrc" />
    </div>
    <ToolExecutionJobs v-else-if="nodeSrc === 'tool_request' && itemId" :tool-execution-id="itemId" />
    <BAlert v-else show variant="info" class="mb-0">No details available for this node.</BAlert>
</template>
