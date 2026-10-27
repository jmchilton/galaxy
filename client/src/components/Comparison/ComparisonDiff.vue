<script setup lang="ts">
import { faTimes } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, ref } from "vue";

import type { ComparisonColumn, ComparisonQuery, ComparisonRow } from "@/api/comparisons";

import { type CellComparison, compareCells, compareMeta } from "./comparisonChanges";
import { type CellDisplay, META_FIELDS, META_LABELS, type MetaField, noJobReason, rowJob } from "./comparisonUtils";

import ComparisonCell from "./cells/ComparisonCell.vue";
import ComparisonColumnLabel from "./ComparisonColumnLabel.vue";
import ComparisonMetaCell from "./ComparisonMetaCell.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import Heading from "@/components/Common/Heading.vue";
import JobParametersDiff from "@/components/JobParameters/JobParametersDiff.vue";

const props = withDefaults(
    defineProps<{
        /** The two runs, in table order. */
        rows: [ComparisonRow, ComparisonRow];
        columns: ComparisonColumn[];
        query: ComparisonQuery;
        /** Each column's cell display, as the table shows it. */
        displays: Record<string, CellDisplay>;
        currentRunId?: string;
        requestedMetadata?: string[];
        loading?: boolean;
    }>(),
    { currentRunId: undefined, requestedMetadata: () => [], loading: false },
);

const emit = defineEmits<{
    (e: "close"): void;
}>();

const onlyDifferences = ref(true);

interface DiffLine {
    key: string;
    comparison: CellComparison;
    meta?: MetaField;
    column?: ComparisonColumn;
}

const metaFields = computed(() => META_FIELDS[props.query.kind]);
const anchorField = computed(() => metaFields.value[0]!);

const lines = computed<DiffLine[]>(() => {
    const [a, b] = props.rows;
    return [
        ...metaFields.value.slice(1).map((meta) => ({ key: meta, meta, comparison: compareMeta(meta, a, b) })),
        ...props.columns.map((column) => ({
            key: column.key,
            column,
            comparison: compareCells(a.cells[column.key], b.cells[column.key], column, props.displays[column.key]!),
        })),
    ];
});
const differing = computed(() => lines.value.filter((line) => line.comparison === "differs").length);
const shownLines = computed(() =>
    onlyDifferences.value ? lines.value.filter((line) => line.comparison !== "same") : lines.value,
);

const UNCOMPARED_TITLE = "Every run makes new outputs; show this column's value or metadata to compare it";

/** The job each side's parameters come from, or why it has none. */
const sides = computed(() =>
    props.rows.map((row) => {
        const job = rowJob(row);
        const reason = noJobReason(row) ?? (job?.jobId ? undefined : "This step ran a subworkflow.");
        return { jobId: job?.jobId, jobCount: job?.jobCount, reason };
    }),
);
const isInvocationKind = computed(() => props.query.kind === "output_runs");
const batchNote = computed(() =>
    sides.value
        .map((side, index) =>
            side.jobId && side.jobCount ? `Run ${"AB"[index]} is a batch of ${side.jobCount} jobs: job 1 shown.` : "",
        )
        .filter(Boolean)
        .join(" "),
);
</script>

<template>
    <section class="comparison-diff card mb-2" aria-label="Differences between the selected runs">
        <div class="card-header d-flex flex-wrap align-items-center py-1 px-2">
            <Heading size="sm" class="mb-0 mr-3">Selected runs</Heading>
            <span class="comparison-diff-summary text-muted small mr-auto">
                {{ differing ? `${differing} of ${lines.length} fields differ` : "No differences in these fields" }}
            </span>
            <GCheckbox v-model="onlyDifferences" class="comparison-diff-only mr-2 mb-0" switch size="small">
                Only differences
            </GCheckbox>
            <GButton
                class="comparison-diff-close"
                transparent
                icon-only
                size="small"
                title="Close the comparison"
                aria-label="Close the comparison"
                @click="emit('close')">
                <FontAwesomeIcon :icon="faTimes" fixed-width />
            </GButton>
        </div>
        <div class="card-body p-2">
            <table class="comparison-diff-table table table-sm mb-2">
                <thead>
                    <tr>
                        <th class="comparison-diff-field" />
                        <th v-for="(row, index) in rows" :key="row.run.id" :data-diff-run="row.run.id">
                            <span class="comparison-diff-side badge badge-secondary mr-1">{{ "AB"[index] }}</span>
                            <ComparisonMetaCell
                                :field="anchorField"
                                :row="row"
                                :query="query"
                                :current="Boolean(currentRunId) && row.run.id === currentRunId" />
                        </th>
                    </tr>
                </thead>
                <tbody>
                    <tr
                        v-for="line in shownLines"
                        :key="line.key"
                        :data-diff-key="line.key"
                        :class="`comparison-diff-${line.comparison}`"
                        :title="line.comparison === 'uncompared' ? UNCOMPARED_TITLE : undefined">
                        <th scope="row" class="comparison-diff-field font-weight-normal">
                            <ComparisonColumnLabel v-if="line.column" :column="line.column" />
                            <span v-else class="font-weight-bold">{{ META_LABELS[line.meta!] }}</span>
                        </th>
                        <td v-for="row in rows" :key="row.run.id">
                            <ComparisonCell
                                v-if="line.column"
                                :cell="row.cells[line.column.key]"
                                :row="row"
                                :display="displays[line.column.key]!"
                                :requested-metadata="requestedMetadata"
                                :loading="loading" />
                            <ComparisonMetaCell v-else :field="line.meta!" :row="row" :query="query" />
                        </td>
                    </tr>
                </tbody>
            </table>
            <p v-if="!shownLines.length" class="comparison-diff-none text-muted small">
                The selected runs show the same values in every field.
            </p>

            <Heading size="sm" separator>Job parameters</Heading>
            <GAlert v-if="isInvocationKind" variant="info" show class="mb-0">
                A workflow run has no single job. Its inputs and parameters are compared above.
            </GAlert>
            <template v-else-if="sides[0]!.jobId && sides[1]!.jobId">
                <p v-if="batchNote" class="comparison-diff-batch text-muted small mb-1">{{ batchNote }}</p>
                <JobParametersDiff
                    :job-id-a="sides[0]!.jobId"
                    :job-id-b="sides[1]!.jobId"
                    label-a="Run A"
                    label-b="Run B"
                    :only-differences="onlyDifferences" />
            </template>
            <GAlert v-else class="comparison-diff-no-job mb-0" variant="info" show>
                Parameters can only be compared between two runs with jobs.
                <template v-for="(side, index) in sides" :key="index">
                    <span v-if="side.reason" class="d-block"> Run {{ "AB"[index] }}: {{ side.reason }} </span>
                </template>
            </GAlert>
        </div>
    </section>
</template>

<style scoped lang="scss">
.comparison-diff-table {
    td,
    th {
        vertical-align: middle;
        white-space: normal;
    }
    .comparison-diff-field {
        width: 12rem;
    }
    .comparison-diff-differs > td {
        background: var(--color-yellow-200);
    }
    .comparison-diff-differs > th {
        box-shadow: inset 3px 0 0 var(--color-yellow-600);
    }
    .comparison-diff-uncompared > td {
        color: var(--color-grey-600);
    }
}
</style>
