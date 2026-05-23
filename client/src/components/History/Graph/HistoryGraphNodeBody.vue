<script setup lang="ts">
import { BAlert } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { GalaxyApi } from "@/api";
import type { GraphNode } from "@/components/Graph/types";

import GenericHistoryItem from "@/components/History/Content/GenericItem.vue";
import JobInformation from "@/components/JobInformation/JobInformation.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

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

// Tool request -> job ID resolution
const jobId = ref<string | null>(null);
const jobLoading = ref(false);
const jobError = ref<string | null>(null);

watch(
    () => [nodeSrc.value, itemId.value],
    async ([src, id]) => {
        jobId.value = null;
        jobError.value = null;
        if (src !== "tool_request" || !id) {
            return;
        }
        jobLoading.value = true;
        try {
            const { data, error } = await GalaxyApi().GET("/api/tool_requests/{id}", {
                params: { path: { id: id as string } },
            });
            if (error) {
                jobError.value = "Failed to load tool request details.";
            } else if (data.jobs && data.jobs.length > 0) {
                jobId.value = data.jobs[0]!.id;
            } else {
                jobError.value = "No job associated with this tool execution.";
            }
        } catch (e) {
            jobError.value = "Failed to load tool request details.";
        } finally {
            jobLoading.value = false;
        }
    },
    { immediate: true },
);
</script>

<template>
    <div v-if="itemSrc && itemId" :key="itemId">
        <GenericHistoryItem :item-id="itemId" :item-src="itemSrc" />
    </div>
    <div v-else-if="nodeSrc === 'tool_request'">
        <LoadingSpan v-if="jobLoading" message="Loading job details" />
        <BAlert v-else-if="jobError" variant="info" show class="mb-0">{{ jobError }}</BAlert>
        <JobInformation v-else-if="jobId" :job-id="jobId" :include-times="true" />
    </div>
    <BAlert v-else show variant="info" class="mb-0">No details available for this node.</BAlert>
</template>
