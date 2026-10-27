<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonColumn, ComparisonQuery, ComparisonRow } from "@/api/comparisons";

import { rowJob, runLink } from "./comparisonUtils";

import ValueCell from "./cells/ValueCell.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import Heading from "@/components/Common/Heading.vue";
import GenericHistoryItem from "@/components/History/Content/GenericItem.vue";
import JobDetailsTabs from "@/components/History/Graph/JobDetailsTabs.vue";

const props = defineProps<{
    row: ComparisonRow;
    columns: ComparisonColumn[];
    query: ComparisonQuery;
}>();

const outputs = computed(() =>
    props.columns
        .filter((column) => column.role === "output")
        .map((column) => ({ column, cell: props.row.cells[column.key] }))
        .filter(({ cell }) => cell && cell.type !== "missing"),
);

const job = computed(() => rowJob(props.row));
const isInvocationRow = computed(() => props.query.kind === "output_runs");
const link = computed(() => runLink(props.row, props.query));
const openLabel = computed(() => (props.row.run.model === "WorkflowInvocation" ? "Open invocation" : "Open job"));

// As the invocation view counts scheduling done.
const SCHEDULING_ENDED = ["scheduled", "cancelled", "failed", "completed"];
const INPUT_STEP_TYPES = ["data_input", "data_collection_input", "parameter_input"];

/** Why a row of a step or tool run shows no job tabs; undefined when it has a job. */
const noJobMessage = computed(() => {
    const row = props.row;
    const runEnded = row.run.model === "WorkflowInvocation" && SCHEDULING_ENDED.includes(row.run.state);
    if (job.value?.jobCount === 0) {
        return "Mapped over an empty collection: no jobs ran.";
    }
    if (job.value?.jobId || row.subworkflow_invocation_id) {
        return undefined;
    }
    // Steps are "new" or "ready" until scheduled.
    if (["new", "ready"].includes(row.state)) {
        return runEnded ? "This run ended before reaching this step." : "This run has no job for this step yet.";
    }
    if (row.step_type === "pause") {
        if (row.step_action === true) {
            return "Reviewed: the run continued past this pause.";
        }
        if (row.step_action === false) {
            return "Review rejected: the run was cancelled at this pause.";
        }
        return runEnded
            ? "This pause step was not reviewed before the run ended."
            : "Waiting for review: the run is paused at this step.";
    }
    if (row.step_type && INPUT_STEP_TYPES.includes(row.step_type)) {
        return "Input steps run without a job.";
    }
    return "This step ran without a job.";
});
</script>

<template>
    <div class="comparison-row-detail p-2">
        <div class="comparison-row-detail-outputs">
            <Heading size="sm" separator>Outputs</Heading>
            <p v-if="!outputs.length" class="text-muted mb-0">No outputs.</p>
            <div v-for="{ column, cell } in outputs" :key="column.key" class="mb-1">
                <b>{{ column.label }}</b>
                <ValueCell v-if="cell?.type === 'value'" class="ml-1" :value="cell.value" />
                <GenericHistoryItem
                    v-else-if="cell?.type === 'dataset' || cell?.type === 'collection'"
                    :item-id="cell.id"
                    :item-src="cell.type === 'dataset' ? 'hda' : 'hdca'" />
            </div>
        </div>
        <div class="comparison-row-detail-job">
            <Heading size="sm" separator>
                {{ job?.jobCount ? `Job 1 of ${job.jobCount}` : "Job" }}
            </Heading>
            <GAlert v-if="isInvocationRow" variant="info" show class="mb-0">
                A workflow run has no single job. Its inputs and parameters are columns of the table.
            </GAlert>
            <GAlert v-else-if="noJobMessage" class="comparison-row-detail-message mb-0" variant="info" show>
                {{ noJobMessage }}
            </GAlert>
            <GTabs v-else-if="job?.jobId">
                <JobDetailsTabs :job-id="job.jobId" />
            </GTabs>
            <GAlert v-else-if="row.subworkflow_invocation_id" variant="info" show class="mb-0">
                This step ran a subworkflow.
                <router-link
                    class="comparison-row-detail-subworkflow"
                    :to="`/workflows/invocations/${row.subworkflow_invocation_id}`">
                    Open the subworkflow run
                </router-link>
            </GAlert>
            <GButton v-if="link" class="mt-2" size="small" color="blue" outline :to="link">{{ openLabel }}</GButton>
        </div>
    </div>
</template>

<style scoped>
.comparison-row-detail {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr);
    gap: 1rem;
    white-space: normal;
}
@media (max-width: 768px) {
    .comparison-row-detail {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
