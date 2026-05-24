<script setup lang="ts">
import type { IconDefinition } from "@fortawesome/fontawesome-svg-core";
import { faInfoCircle, faSignOutAlt, faSlidersH } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { BAlert } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { GalaxyApi } from "@/api";

import GTab from "@/components/BaseComponents/GTab.vue";
import JobInformation from "@/components/JobInformation/JobInformation.vue";
import JobOutputs from "@/components/JobInformation/JobOutputs.vue";
import JobParameters from "@/components/JobParameters/JobParameters.vue";

interface Props {
    /** Encoded id of the job to display tabs for. */
    jobId: string;
    /** Custom text for the Information tab title. Defaults to "Information". */
    infoTitle?: string;
    /** Custom icon for the Information tab title. Defaults to faInfoCircle. */
    infoIcon?: IconDefinition;
}

const props = defineProps<Props>();

const informationTitle = computed(() => props.infoTitle || "Information");
const informationIcon = computed(() => props.infoIcon || faInfoCircle);

// parameters_display drives the Outputs tab; JobInformation/JobParameters
// fetch their own data via the job-id prop.
const paramsDisplay = ref<{ outputs?: Record<string, unknown[]> } | null>(null);
const hasOutputs = computed(
    () => paramsDisplay.value?.outputs && Object.keys(paramsDisplay.value.outputs).length > 0,
);

watch(
    () => props.jobId,
    async (id) => {
        paramsDisplay.value = null;
        if (!id) {
            return;
        }
        try {
            const { data, error } = await GalaxyApi().GET("/api/jobs/{job_id}/parameters_display", {
                params: { path: { job_id: id } },
            });
            // Drop out-of-order responses.
            if (props.jobId === id && !error) {
                paramsDisplay.value = data ?? null;
            }
        } catch (e) {
            // Graceful — Outputs tab falls through to its empty state.
        }
    },
    { immediate: true },
);
</script>

<template>
    <!-- Wrapping div so the three GTabs share a single template root (Vue 2.7
         doesn't support multi-root templates). GTab children still register
         via inject with the outer GTabs context — the wrapper is layout-neutral. -->
    <div>
        <GTab>
            <template v-slot:title>
                <FontAwesomeIcon :icon="informationIcon" />
                <span class="font-weight-bold text-break">{{ informationTitle }}</span>
            </template>
            <JobInformation :key="jobId" :job-id="jobId" :include-title="false" :include-times="true" />
        </GTab>
        <GTab lazy>
            <template v-slot:title>
                <FontAwesomeIcon :icon="faSlidersH" />
                <span>Parameters</span>
            </template>
            <JobParameters :key="jobId" :job-id="jobId" :include-title="false" :include-outputs="false" />
        </GTab>
        <GTab lazy>
            <template v-slot:title>
                <FontAwesomeIcon :icon="faSignOutAlt" />
                <span>Outputs</span>
            </template>
            <JobOutputs v-if="hasOutputs" :key="jobId" :job-outputs="paramsDisplay?.outputs" paginate />
            <BAlert v-else show variant="info" class="mb-0">No outputs.</BAlert>
        </GTab>
    </div>
</template>

