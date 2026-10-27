<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonColumn, ComparisonQuery, ComparisonRow } from "@/api/comparisons";

import { noJobReason, rowJob, runLink } from "./comparisonUtils";

import ValueCell from "./cells/ValueCell.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GTabs from "@/components/BaseComponents/GTabs.vue";
import Heading from "@/components/Common/Heading.vue";
import GenericHistoryItem from "@/components/History/Content/GenericItem.vue";
import JobDetailsTabs from "@/components/History/Graph/JobDetailsTabs.vue";
import ToolExecutionJobs from "@/components/History/Graph/ToolExecutionJobs.vue";
import JobParametersDiff from "@/components/JobParameters/JobParametersDiff.vue";

const props = defineProps<{
    row: ComparisonRow;
    columns: ComparisonColumn[];
    query: ComparisonQuery;
    /** The viewed run's job, to diff this run's parameters against. */
    currentJobId?: string;
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
const noJobMessage = computed(() => noJobReason(props.row));
const diffJobId = computed(() => {
    const jobId = isInvocationRow.value ? undefined : job.value?.jobId;
    return jobId && props.currentJobId && jobId !== props.currentJobId ? jobId : undefined;
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
            <div v-if="diffJobId && currentJobId" class="comparison-row-detail-parameters">
                <Heading size="sm" separator>Parameters against the run you are viewing</Heading>
                <p v-if="job?.jobCount" class="text-muted small mb-1">Compares job 1 of the batch.</p>
                <JobParametersDiff
                    :job-id-a="diffJobId"
                    :job-id-b="currentJobId"
                    label-a="This run"
                    label-b="Run you are viewing"
                    :only-differences="false" />
            </div>
        </div>
        <div class="comparison-row-detail-job">
            <Heading size="sm" separator>
                {{ job?.jobCount ? `Batch of ${job.jobCount} jobs` : "Job" }}
            </Heading>
            <GAlert v-if="isInvocationRow" variant="info" show class="mb-0">
                A workflow run has no single job. Its inputs and parameters are columns of the table.
            </GAlert>
            <GAlert v-else-if="noJobMessage" class="comparison-row-detail-message mb-0" variant="info" show>
                {{ noJobMessage }}
            </GAlert>
            <ToolExecutionJobs
                v-else-if="job?.jobCount && job.implicitCollectionJobsId"
                :implicit-collection-jobs-id="job.implicitCollectionJobsId"
                :job-count="job.jobCount"
                :initial-job-id="job.jobId" />
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
/* Its space, not the window's: the table's panels may leave it narrow on a wide screen. */
@container (max-width: 768px) {
    .comparison-row-detail {
        grid-template-columns: minmax(0, 1fr);
    }
}
</style>
