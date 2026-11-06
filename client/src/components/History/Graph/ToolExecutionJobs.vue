<script setup lang="ts">
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { computed, ref, toRef, watch } from "vue";

import { useToolExecutionJobs } from "./useToolExecutionJobs";

import JobDetailsTabs from "./JobDetailsTabs.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import JobHeader from "@/components/JobInformation/JobHeader.vue";
import JobPager from "@/components/JobInformation/JobPager.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    /** Encoded tool-execution (tool_request) id whose jobs should be listed. */
    toolExecutionId: string;
    /** Custom text for the Information tab title (forwarded to JobDetailsTabs). */
    infoTitle?: string;
    /** Custom icon for the Information tab title (forwarded to JobDetailsTabs). */
    infoIcon?: IconDefinition;
}

const props = defineProps<Props>();

const { jobs, loading, error } = useToolExecutionJobs(toRef(props, "toolExecutionId"));

const currentIndex = ref(0);
watch(
    () => props.toolExecutionId,
    () => {
        currentIndex.value = 0;
    },
);
const currentJob = computed(() => jobs.value[currentIndex.value] ?? null);
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
                            <JobPager v-model="currentIndex" :job-count="jobs.length" class="mr-2" />
                        </template>
                    </JobHeader>
                </template>
                <JobDetailsTabs :job-id="currentJob.id" :info-title="props.infoTitle" :info-icon="props.infoIcon" />
            </GTabs>
        </template>
    </div>
</template>
