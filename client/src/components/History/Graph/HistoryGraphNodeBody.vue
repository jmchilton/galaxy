<script setup lang="ts">
import axios from "axios";
import { BAlert } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import type { GraphNode } from "@/components/Graph/types";
import { useJobBasic } from "@/composables/useJobBasic";
import { getAppRoot } from "@/onload/loadConfig";

import GTabs from "@/components/BaseComponents/GTabs.vue";
import JobDetailsTabs from "./JobDetailsTabs.vue";
import ToolExecutionJobs from "./ToolExecutionJobs.vue";
import RerunJobButton from "@/components/JobInformation/RerunJobButton.vue";
import JobState from "@/components/JobStates/JobState.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    /** The graph node to render details for. */
    node: GraphNode;
}

const props = defineProps<Props>();

const nodeSrc = computed(() => (props.node.data?.src as string) ?? null);
const itemId = computed(() => (props.node.data?.itemId as string) ?? null);
const isDatasetLike = computed(() => nodeSrc.value === "hda" || nodeSrc.value === "hdca");

// For dataset/collection nodes, resolve the creating job + fetch its basic
// details so the same JobState badge / RerunJobButton chrome the tool
// execution view shows can render in the GTabs nav-end.
const creatingJobId = ref<string | null>(null);
const lookupLoading = ref(false);
const lookupError = ref<string | null>(null);

// Job details for the state badge — shared jobStore cache via useJobBasic.
const { job } = useJobBasic(creatingJobId);

watch(
    () => [nodeSrc.value, itemId.value],
    async ([src, id]) => {
        creatingJobId.value = null;
        lookupError.value = null;
        if (!id || (src !== "hda" && src !== "hdca")) {
            return;
        }
        lookupLoading.value = true;
        try {
            if (src === "hda") {
                const { data } = await axios.get(`${getAppRoot()}api/datasets/${id}`);
                if (data.creating_job) {
                    creatingJobId.value = data.creating_job;
                } else {
                    lookupError.value = "No creating job recorded for this dataset.";
                }
            } else {
                const { data } = await axios.get(`${getAppRoot()}api/dataset_collections/${id}`);
                if (data.job_source_type === "Job" && data.job_source_id) {
                    creatingJobId.value = data.job_source_id;
                } else {
                    lookupError.value =
                        "This collection wasn't produced by a single job (batch run or workflow). Open an element to see its job.";
                }
            }
        } catch (e) {
            lookupError.value = "Failed to resolve the creating job.";
        } finally {
            lookupLoading.value = false;
        }
    },
    { immediate: true },
);

</script>

<template>
    <ToolExecutionJobs v-if="nodeSrc === 'tool_request' && itemId" :tool-execution-id="itemId" />
    <LoadingSpan v-else-if="isDatasetLike && lookupLoading" message="Loading job details" />
    <BAlert v-else-if="isDatasetLike && lookupError" variant="info" show class="mb-0">{{ lookupError }}</BAlert>
    <GTabs v-else-if="isDatasetLike && creatingJobId">
        <template v-slot:nav-end>
            <JobState v-if="job" :job="job" class="mr-2" />
            <RerunJobButton v-if="job" :job-id="creatingJobId" outline />
        </template>
        <JobDetailsTabs :key="creatingJobId" :job-id="creatingJobId" />
    </GTabs>
    <BAlert v-else show variant="info" class="mb-0">No details available for this node.</BAlert>
</template>
