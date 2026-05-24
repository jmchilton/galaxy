<script setup lang="ts">
import {
    faChevronLeft,
    faChevronRight,
    faInfoCircle,
    faSignInAlt,
    faSignOutAlt,
} from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import axios from "axios";
import { BAlert, BButton, BButtonGroup } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { GalaxyApi } from "@/api";
import { getAppRoot } from "@/onload/loadConfig";

import GTab from "@/components/BaseComponents/GTab.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import JobInformation from "@/components/JobInformation/JobInformation.vue";
import JobOutputs from "@/components/JobInformation/JobOutputs.vue";
import JobParameters from "@/components/JobParameters/JobParameters.vue";
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

// parameters_display payload for the currently-selected job — drives the
// Outputs tab (its `outputs` field is the {name: JobOutput[]} shape that
// JobOutputs expects, with proper label/value pairs). The Parameters tab
// uses JobParameters which fetches the same endpoint internally; that
// duplicate is cheaper than refactoring JobParameters to accept pre-fetched
// data.
const paramsDisplay = ref<{ outputs?: Record<string, unknown[]> } | null>(null);

const currentJob = computed(() => jobs.value[currentIndex.value] ?? null);
const hasMany = computed(() => jobs.value.length > 1);
const hasOutputs = computed(
    () => paramsDisplay.value?.outputs && Object.keys(paramsDisplay.value.outputs).length > 0,
);

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

// Fetch parameters_display for the Outputs tab whenever the user navigates
// to a different job.
watch(
    () => currentJob.value?.id,
    async (id) => {
        paramsDisplay.value = null;
        if (!id) {
            return;
        }
        try {
            const { data } = await axios.get(`${getAppRoot()}api/jobs/${id}/parameters_display`);
            paramsDisplay.value = data;
        } catch (e) {
            // Graceful — Outputs tab falls through to its empty state.
        }
    },
    { immediate: true },
);

function prev() {
    if (currentIndex.value > 0) {
        currentIndex.value -= 1;
    }
}

function next() {
    if (currentIndex.value < jobs.value.length - 1) {
        currentIndex.value += 1;
    }
}
</script>

<template>
    <div>
        <LoadingSpan v-if="loading" message="Loading job details" />
        <BAlert v-else-if="error" variant="info" show class="mb-0">{{ error }}</BAlert>
        <template v-else-if="currentJob">
            <div v-if="hasMany" class="d-flex align-items-center mb-2">
                <span class="font-weight-bold">Job {{ currentIndex + 1 }} of {{ jobs.length }}</span>
                <BButtonGroup size="sm" class="ml-auto">
                    <BButton :disabled="currentIndex === 0" variant="outline-secondary" @click="prev">
                        <FontAwesomeIcon :icon="faChevronLeft" fixed-width />
                    </BButton>
                    <BButton :disabled="currentIndex >= jobs.length - 1" variant="outline-secondary" @click="next">
                        <FontAwesomeIcon :icon="faChevronRight" fixed-width />
                    </BButton>
                </BButtonGroup>
            </div>
            <GTabs>
                <GTab>
                    <template v-slot:title>
                        <FontAwesomeIcon :icon="faInfoCircle" />
                        <span>Information</span>
                    </template>
                    <JobInformation :job-id="currentJob.id" :include-times="true" />
                </GTab>
                <GTab lazy>
                    <template v-slot:title>
                        <FontAwesomeIcon :icon="faSignInAlt" />
                        <span>Inputs</span>
                    </template>
                    <JobParameters :job-id="currentJob.id" :include-outputs="false" />
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
