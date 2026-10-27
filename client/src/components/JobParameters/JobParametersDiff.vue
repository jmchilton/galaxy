<script setup lang="ts">
import { computed, watch } from "vue";

import { useJobParametersStore } from "@/stores/jobParametersStore";
import { errorMessageAsString } from "@/utils/simple-error";

import { diffJobParameters } from "./jobParameterDiff";

import GAlert from "@/components/BaseComponents/GAlert.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const props = withDefaults(
    defineProps<{
        jobIdA: string;
        jobIdB: string;
        /** Column headings for the two jobs. */
        labelA?: string;
        labelB?: string;
        onlyDifferences?: boolean;
    }>(),
    { labelA: "A", labelB: "B", onlyDifferences: false },
);

const store = useJobParametersStore();

watch(
    () => [props.jobIdA, props.jobIdB],
    (ids) => ids.forEach((id) => id && store.fetchJobParameters({ id })),
    { immediate: true },
);

const parametersA = computed(() => store.getJobParameters(props.jobIdA));
const parametersB = computed(() => store.getJobParameters(props.jobIdB));
const loading = computed(
    () => store.isLoadingJobParameters(props.jobIdA) || store.isLoadingJobParameters(props.jobIdB),
);
const error = computed(() => {
    const failed = store.getJobParametersLoadError(props.jobIdA) ?? store.getJobParametersLoadError(props.jobIdB);
    return failed ? errorMessageAsString(failed, "Failed to load job parameters.") : undefined;
});

const entries = computed(() =>
    parametersA.value && parametersB.value
        ? diffJobParameters(parametersA.value.parameters, parametersB.value.parameters)
        : [],
);
const shown = computed(() => (props.onlyDifferences ? entries.value.filter((entry) => entry.differs) : entries.value));
const differing = computed(() => entries.value.filter((entry) => entry.differs).length);
</script>

<template>
    <div class="job-parameters-diff">
        <GAlert v-if="error" variant="danger" show class="mb-0">{{ error }}</GAlert>
        <LoadingSpan v-else-if="loading || !parametersA || !parametersB" message="Loading job parameters" />
        <template v-else>
            <p class="job-parameters-diff-summary text-muted small mb-1">
                {{ differing ? `${differing} of ${entries.length} parameters differ.` : "All parameters match." }}
            </p>
            <table v-if="shown.length" class="table table-sm mb-0">
                <thead>
                    <tr>
                        <th>Parameter</th>
                        <th>{{ labelA }}</th>
                        <th>{{ labelB }}</th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="entry in shown"
                        :key="entry.key"
                        :class="{ 'job-parameters-diff-changed': entry.differs }">
                        <td :style="{ 'padding-left': `${(entry.depth - 1) * 10 + 4}px` }" :title="entry.path">
                            {{ entry.label }}
                        </td>
                        <td
                            v-for="(side, index) in [
                                { value: entry.a, notes: entry.notesA },
                                { value: entry.b, notes: entry.notesB },
                            ]"
                            :key="index">
                            <span v-if="side.value === undefined" class="text-muted font-italic">absent</span>
                            <template v-else>{{ side.value }}</template>
                            <em v-if="side.notes" class="job-parameters-diff-notes text-muted small">
                                {{ side.notes }}
                            </em>
                        </td>
                    </tr>
                </tbody>
            </table>
        </template>
    </div>
</template>

<style scoped>
.job-parameters-diff td {
    white-space: normal;
    word-break: break-word;
}
.job-parameters-diff-changed td {
    background: var(--color-yellow-200);
}
</style>
