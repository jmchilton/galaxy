<script setup lang="ts">
import { BPagination } from "bootstrap-vue";
import { computed, ref, watch } from "vue";

import { type ComparisonTable as ComparisonTableModel, fetchStepRuns, type StepRunsParams } from "@/api/comparisons";

import { requestedMetadata } from "./comparisonUtils";
import { useComparisonDisplay, useComparisonFetch } from "./useComparison";

import ComparisonTable from "./ComparisonTable.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const PER_PAGE = 25;

const props = withDefaults(
    defineProps<{
        /** StoredWorkflow id, or a Workflow version id with `instance`. */
        workflowId: string;
        instance?: boolean;
        stepLabel?: string | null;
        /** The invocation being viewed, highlighted in the table. */
        currentInvocationId?: string;
    }>(),
    { instance: false, stepLabel: undefined, currentInvocationId: undefined },
);

const page = ref(1);
const table = ref<ComparisonTableModel>();
// Keyed by the stored workflow the server resolved, so every version shares one setting.
const storageKey = computed(() => {
    const query = table.value?.query;
    return query?.kind === "step_runs" ? `step_runs:${query.workflow_id}:${query.step_label}` : undefined;
});
const { transpose, columnDisplay, visibleColumns, toggleColumn, resetColumns } = useComparisonDisplay(
    storageKey,
    table,
);

const params = computed<StepRunsParams | undefined>(() => {
    if (!props.stepLabel) {
        return undefined;
    }
    const metadata = requestedMetadata(columnDisplay.value);
    return {
        workflow_id: props.workflowId,
        instance: props.instance || undefined,
        step_label: props.stepLabel,
        limit: PER_PAGE,
        offset: (page.value - 1) * PER_PAGE,
        metadata_elements: metadata.length ? metadata : undefined,
    };
});
const { total, loading, error } = useComparisonFetch(params, fetchStepRuns, table);

watch(
    () => [props.workflowId, props.stepLabel],
    () => {
        page.value = 1;
    },
);

const summary = computed(() => {
    const rows = table.value?.rows.length ?? 0;
    if (!rows) {
        return "";
    }
    const first = (page.value - 1) * PER_PAGE + 1;
    return `Showing ${first}–${first + rows - 1} of ${total.value} · newest first · your runs only`;
});
</script>

<template>
    <div class="step-runs-tab">
        <GAlert v-if="!stepLabel" variant="info" show>
            <b>Label this step to compare its runs.</b>
            Runs are matched across workflow versions by step label. Add a label in the workflow editor and runs from
            that version on will show here.
        </GAlert>
        <template v-else>
            <GAlert v-if="error" variant="danger" show>{{ error }}</GAlert>
            <LoadingSpan v-if="loading && !table" message="Loading runs of this step" />
            <template v-if="table">
                <ComparisonTable
                    v-model:transpose="transpose"
                    v-model:column-display="columnDisplay"
                    :table="table"
                    :visible-columns="visibleColumns"
                    :current-run-id="currentInvocationId"
                    :loading="loading"
                    empty-message="This step has no runs yet."
                    @toggle-column="toggleColumn"
                    @reset-columns="resetColumns" />
                <div class="d-flex flex-wrap justify-content-between align-items-center mt-2">
                    <small class="step-runs-summary text-muted">{{ summary }}</small>
                    <BPagination
                        v-if="total > PER_PAGE"
                        v-model="page"
                        :total-rows="total"
                        :per-page="PER_PAGE"
                        size="sm"
                        class="mb-0"
                        aria-label="Pages of runs" />
                </div>
            </template>
        </template>
    </div>
</template>
