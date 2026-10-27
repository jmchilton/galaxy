<script setup lang="ts">
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { BPagination } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { type ExecutionJobsSource, useExecutionJobs } from "./useExecutionJobs";

import JobDetailsTabs from "./JobDetailsTabs.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import JobHeader from "@/components/JobInformation/JobHeader.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    /** Encoded tool-execution (tool_request) id whose jobs should be listed. */
    toolExecutionId?: string;
    /** Encoded id of a mapped-over batch (ImplicitCollectionJobs) whose jobs should be listed instead. */
    implicitCollectionJobsId?: string;
    /** The job to open on, e.g. the one a summary already showed; the first otherwise. */
    initialJobId?: string;
    /** Custom text for the Information tab title (forwarded to JobDetailsTabs). */
    infoTitle?: string;
    /** Custom icon for the Information tab title (forwarded to JobDetailsTabs). */
    infoIcon?: IconDefinition;
}

const props = defineProps<Props>();

const source = computed<ExecutionJobsSource | undefined>(() => {
    if (props.toolExecutionId) {
        return { toolRequestId: props.toolExecutionId };
    }
    return props.implicitCollectionJobsId ? { implicitCollectionJobsId: props.implicitCollectionJobsId } : undefined;
});
const { jobs, loading, error } = useExecutionJobs(source);

const currentIndex = ref(0);
watch(jobs, (loaded) => {
    currentIndex.value = Math.max(
        loaded.findIndex((job) => job.id === props.initialJobId),
        0,
    );
});
const currentJob = computed(() => jobs.value[currentIndex.value] ?? null);

const hasMany = computed(() => jobs.value.length > 1);

// BPagination is 1-indexed; bridge to the 0-indexed currentIndex.
const paginationPage = computed<number>({
    get: () => currentIndex.value + 1,
    set: (val: number) => {
        currentIndex.value = val - 1;
    },
});
</script>

<template>
    <div>
        <LoadingSpan v-if="loading" message="Loading job details" />
        <GAlert v-else-if="error" variant="info" show class="mb-0">{{ error }}</GAlert>
        <template v-else-if="currentJob">
            <GTabs>
                <template v-slot:nav-end>
                    <JobHeader v-if="currentJob" :job-id="currentJob.id" no-tool-name no-hr>
                        <template v-slot:pagination>
                            <BPagination
                                v-if="hasMany"
                                v-model="paginationPage"
                                :total-rows="jobs.length"
                                :per-page="1"
                                size="sm"
                                :limit="3"
                                first-number
                                last-number
                                hide-goto-end-buttons
                                class="mb-0 mr-2" />
                        </template>
                    </JobHeader>
                </template>
                <JobDetailsTabs :job-id="currentJob.id" :info-title="props.infoTitle" :info-icon="props.infoIcon" />
            </GTabs>
        </template>
    </div>
</template>
