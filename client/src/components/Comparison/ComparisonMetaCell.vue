<script setup lang="ts">
import { faStar } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed } from "vue";

import type { ComparisonQuery, ComparisonRow } from "@/api/comparisons";

import { historyLink, type MetaField, rowJob, runLink, versionLabel } from "./comparisonUtils";

import StateLabel from "./cells/StateLabel.vue";
import UtcDate from "@/components/UtcDate.vue";

const props = defineProps<{
    field: MetaField;
    row: ComparisonRow;
    query: ComparisonQuery;
    current?: boolean;
}>();

const link = computed(() => runLink(props.row, props.query));
const job = computed(() => rowJob(props.row));
const batchNote = computed(() =>
    job.value?.jobCount !== undefined ? `mapped over ${job.value.jobCount} jobs · details from job 1` : "",
);
const runKind = computed(() => {
    const run = props.row.run;
    return run.model === "ImplicitCollectionJobs" ? `batch of ${run.job_count} jobs` : "job";
});
const via = computed(() => {
    const via = props.row.via;
    if (!via) {
        return "";
    }
    return ["in workflow", via.workflow_name, via.step_label ? `step ${via.step_label}` : ""].filter(Boolean).join(" ");
});
</script>

<template>
    <span v-if="field === 'invoked' || field === 'run'" class="comparison-meta-run">
        <router-link v-if="link" :to="link" class="comparison-run-link">
            <UtcDate :date="row.create_time" mode="elapsed" />
        </router-link>
        <UtcDate v-else :date="row.create_time" mode="elapsed" />
        <span v-if="current" class="comparison-current-badge badge badge-info ml-1" title="The run you are viewing">
            <FontAwesomeIcon :icon="faStar" /> this run
        </span>
        <small v-if="field === 'run'" class="d-block text-muted">{{ runKind }} {{ via }}</small>
        <small v-if="batchNote" class="d-block text-muted">{{ batchNote }}</small>
        <small v-if="row.subworkflow_invocation_id" class="d-block">
            <router-link :to="`/workflows/invocations/${row.subworkflow_invocation_id}`">subworkflow run</router-link>
        </small>
    </span>
    <span v-else-if="field === 'version'">{{ versionLabel(row.version) }}</span>
    <code v-else-if="field === 'tool_version'" class="text-reset">{{ row.tool_version }}</code>
    <StateLabel
        v-else-if="field === 'state'"
        class="comparison-state"
        :class="`comparison-state-${row.state}`"
        :state="row.state" />
    <span v-else-if="field === 'reused'">
        <span v-if="row.reused === 'yes'" class="badge badge-info" title="Job cache: copied from an earlier job">
            reused
        </span>
        <span
            v-else-if="row.reused === 'partial'"
            class="badge badge-info"
            title="Job cache: some jobs in the batch were copied">
            partly reused
        </span>
    </span>
    <span v-else-if="field === 'history'">
        <router-link :to="historyLink(row.history.id)">{{ row.history.name || row.history.id }}</router-link>
        <span v-if="row.history.purged" class="badge badge-danger ml-1">purged history</span>
        <span v-else-if="row.history.deleted" class="badge badge-danger ml-1">deleted history</span>
    </span>
</template>
