<script setup lang="ts">
import { faInfoCircle, faSignOutAlt, faSlidersH } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import axios from "axios";
import { BAlert, BPagination } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { GalaxyApi } from "@/api";
import type { JobBaseModel } from "@/api/jobs";
import { getAppRoot } from "@/onload/loadConfig";

import GTab from "@/components/BaseComponents/GTab.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import JobInformation from "@/components/JobInformation/JobInformation.vue";
import JobOutputs from "@/components/JobInformation/JobOutputs.vue";
import RerunJobButton from "@/components/JobInformation/RerunJobButton.vue";
import JobParameters from "@/components/JobParameters/JobParameters.vue";
import JobState from "@/components/JobStates/JobState.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

interface Props {
    /** Encoded tool-execution (tool_request) id whose jobs should be listed. */
    toolExecutionId: string;
}

const props = defineProps<Props>();

const jobs = ref<{ id: string }[]>([]);
const currentIndex = ref(0);
const loading = ref(false);
const error = ref<string | null>(null);

// Currently-selected job, fetched on navigation. `job` drives the state badge
// in the tab nav-end; `paramsDisplay` drives the Outputs tab.
const job = ref<JobBaseModel | null>(null);
const paramsDisplay = ref<{ outputs?: Record<string, unknown[]> } | null>(null);

const currentJob = computed(() => jobs.value[currentIndex.value] ?? null);
const hasMany = computed(() => jobs.value.length > 1);
const hasOutputs = computed(
    () => paramsDisplay.value?.outputs && Object.keys(paramsDisplay.value.outputs).length > 0,
);

// BPagination is 1-indexed; bridge to the 0-indexed currentIndex.
const paginationPage = computed<number>({
    get: () => currentIndex.value + 1,
    set: (val: number) => {
        currentIndex.value = val - 1;
    },
});

watch(
    () => props.toolExecutionId,
    async (id) => {
        jobs.value = [];
        currentIndex.value = 0;
        error.value = null;
        if (!id) {
            return;
        }
        loading.value = true;
        try {
            const { data, error: apiError } = await GalaxyApi().GET("/api/tool_requests/{id}", {
                params: { path: { id } },
            });
            if (apiError) {
                error.value = "Failed to load tool execution details.";
            } else if (data.jobs && data.jobs.length > 0) {
                jobs.value = data.jobs;
            } else {
                error.value = "No job associated with this tool execution.";
            }
        } catch (e) {
            error.value = "Failed to load tool execution details.";
        } finally {
            loading.value = false;
        }
    },
    { immediate: true },
);

watch(
    () => currentJob.value?.id,
    async (id) => {
        job.value = null;
        paramsDisplay.value = null;
        if (!id) {
            return;
        }
        try {
            const [{ data: jobData }, { data: paramsData }] = await Promise.all([
                axios.get(`${getAppRoot()}api/jobs/${id}`),
                axios.get(`${getAppRoot()}api/jobs/${id}/parameters_display`),
            ]);
            job.value = jobData;
            paramsDisplay.value = paramsData;
        } catch (e) {
            // Graceful — tabs/badges fall through to their empty states.
        }
    },
    { immediate: true },
);
</script>

<template>
    <div>
        <LoadingSpan v-if="loading" message="Loading job details" />
        <BAlert v-else-if="error" variant="info" show class="mb-0">{{ error }}</BAlert>
        <template v-else-if="currentJob">
            <GTabs>
                <template v-slot:nav-end>
                    <JobState v-if="job" :job="job" class="mr-2" />
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
                    <RerunJobButton v-if="job" :job-id="currentJob.id" outline />
                </template>
                <GTab>
                    <template v-slot:title>
                        <FontAwesomeIcon :icon="faInfoCircle" />
                        <span>Information</span>
                    </template>
                    <JobInformation :job-id="currentJob.id" :include-title="false" :include-times="true" />
                </GTab>
                <GTab lazy>
                    <template v-slot:title>
                        <FontAwesomeIcon :icon="faSlidersH" />
                        <span>Parameters</span>
                    </template>
                    <JobParameters :job-id="currentJob.id" :include-title="false" :include-outputs="false" />
                </GTab>
                <GTab lazy>
                    <template v-slot:title>
                        <FontAwesomeIcon :icon="faSignOutAlt" />
                        <span>Outputs</span>
                    </template>
                    <JobOutputs v-if="hasOutputs" :job-outputs="paramsDisplay?.outputs" paginate />
                    <BAlert v-else show variant="info" class="mb-0">No outputs.</BAlert>
                </GTab>
            </GTabs>
        </template>
    </div>
</template>
