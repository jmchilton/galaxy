<script setup lang="ts">
import { faExternalLinkAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, ref, watch } from "vue";

import { type ComparisonTable as ComparisonTableModel, fetchStepRuns, type StepRunsParams } from "@/api/comparisons";

import { comparisonPath, DEFAULT_LIMIT, displayStorageKey } from "./comparisonQuery";
import { requestedMetadata } from "./comparisonUtils";
import { useComparisonDisplay, useComparisonFetch } from "./useComparison";

import ComparisonPager from "./ComparisonPager.vue";
import ComparisonTable from "./ComparisonTable.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import LoadingSpan from "@/components/LoadingSpan.vue";

const props = withDefaults(
    defineProps<{
        /** StoredWorkflow id, or a Workflow version id with `instance`. */
        workflowId: string;
        instance?: boolean;
        /** The StoredWorkflow behind an `instance` id, if known; display preferences load before the first fetch. */
        storedWorkflowId?: string;
        stepLabel?: string | null;
        /** The invocation being viewed, highlighted in the table. */
        currentInvocationId?: string;
    }>(),
    { instance: false, storedWorkflowId: undefined, stepLabel: undefined, currentInvocationId: undefined },
);

const offset = ref(0);
const table = ref<ComparisonTableModel>();
// Keyed by the stored workflow, so every version shares one setting; the echoed id only when not given.
const storageKey = computed(() => {
    const storedId = props.storedWorkflowId ?? (props.instance ? undefined : props.workflowId);
    if (storedId && props.stepLabel) {
        return displayStorageKey({ kind: "step_runs", workflow_id: storedId, step_label: props.stepLabel });
    }
    return table.value ? displayStorageKey(table.value.query) : undefined;
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
        limit: DEFAULT_LIMIT,
        offset: offset.value,
        metadata_elements: metadata.length ? metadata : undefined,
    };
});
const { total, loading, error, reload } = useComparisonFetch(params, fetchStepRuns, table);

watch(
    () => [props.workflowId, props.stepLabel],
    () => {
        offset.value = 0;
    },
);

// The echoed stored workflow id, so the page needs no `instance`.
const pageLink = computed(() => {
    const query = table.value?.query;
    return query?.kind === "step_runs"
        ? comparisonPath("step_runs", { workflow_id: query.workflow_id, step_label: query.step_label })
        : undefined;
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
            <GAlert v-if="error" variant="danger" show>
                {{ error }}
                <GButton class="comparison-retry ml-2" size="small" outline @click="reload">Retry</GButton>
            </GAlert>
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
                    @reset-columns="resetColumns">
                    <template v-slot:toolbar>
                        <GButton
                            v-if="pageLink"
                            class="comparison-view-all"
                            size="small"
                            color="blue"
                            outline
                            :to="pageLink"
                            title="Open these runs as a full page, with filters and a shareable link">
                            <FontAwesomeIcon :icon="faExternalLinkAlt" />
                            View all in a page
                        </GButton>
                    </template>
                </ComparisonTable>
                <ComparisonPager
                    v-model:offset="offset"
                    :total="total"
                    :limit="DEFAULT_LIMIT"
                    :loaded-offset="table.query.offset"
                    :sort-by="table.query.sort_by"
                    :sort-desc="table.query.sort_desc"
                    :row-count="table.rows.length" />
            </template>
        </template>
    </div>
</template>
