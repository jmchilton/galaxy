<script setup lang="ts">
import { faAngleDown, faAngleRight, faColumns, faDownload, faExchangeAlt } from "@fortawesome/free-solid-svg-icons";
import { FontAwesomeIcon } from "@fortawesome/vue-fontawesome";
import { computed, ref, watch } from "vue";

import type { ComparisonColumn, ComparisonRow, ComparisonTable } from "@/api/comparisons";
import { downloadBlob } from "@/utils/download";

import { changedCells } from "./comparisonChanges";
import { exportBlob, exportFilename, type ExportFormat, exportLines } from "./comparisonExport";
import { type CellDisplay, displayFor, fieldKeys, META_FIELDS, META_LABELS, type MetaField } from "./comparisonUtils";

import ComparisonCell from "./cells/ComparisonCell.vue";
import ComparisonColumnHeader from "./ComparisonColumnHeader.vue";
import ComparisonDiff from "./ComparisonDiff.vue";
import ComparisonMetaCell from "./ComparisonMetaCell.vue";
import ComparisonRowDetail from "./ComparisonRowDetail.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";
import GButton from "@/components/BaseComponents/GButton.vue";
import GCheckbox from "@/components/BaseComponents/GCheckbox.vue";
import GDropdown from "@/components/BaseComponents/GDropdown.vue";
import GDropdownItem from "@/components/BaseComponents/GDropdownItem.vue";
import GTable from "@/components/Common/GTable.vue";
import ListHeader from "@/components/Common/ListHeader.vue";

const props = withDefaults(
    defineProps<{
        table: ComparisonTable;
        /** Runs as columns instead of rows. */
        transpose?: boolean;
        /** Cell display per column key; columns without an entry use their default. */
        columnDisplay?: Record<string, CellDisplay>;
        /** Keys of the shown meta fields and data columns. */
        visibleColumns: string[];
        /** The run to highlight, e.g. the invocation being viewed. */
        currentRunId?: string;
        loading?: boolean;
        emptyMessage?: string;
    }>(),
    {
        transpose: false,
        columnDisplay: () => ({}),
        currentRunId: undefined,
        loading: false,
        emptyMessage: "No runs to compare.",
    },
);

const emit = defineEmits<{
    (e: "update:transpose", value: boolean): void;
    (e: "update:columnDisplay", value: Record<string, CellDisplay>): void;
    (e: "toggle-column", key: string): void;
    (e: "reset-columns"): void;
}>();

interface RunItem {
    runId: string;
    row: ComparisonRow;
    current: boolean;
    class?: string;
    cellClass?: Record<string, string>;
}

interface LineItem {
    lineKey: string;
    meta?: MetaField;
    column?: ComparisonColumn;
    cellClass?: Record<string, string>;
}

const CHANGED_CLASS = "comparison-cell-changed";
const CHANGED_TITLE = "Differs from the run you are viewing";

const metaFields = computed(() => META_FIELDS[props.table.query.kind]);
/** The field that anchors each run: it links to the run and is never hidden. */
const anchorField = computed(() => metaFields.value[0]!);
const optionalMetaFields = computed(() => metaFields.value.slice(1));
const visibleMetaFields = computed(() => optionalMetaFields.value.filter((f) => props.visibleColumns.includes(f)));
const visibleDataColumns = computed(() => props.table.columns.filter((c) => props.visibleColumns.includes(c.key)));
const keys = computed(() => fieldKeys(props.table.columns));

const columnOptions = computed(() => [
    ...optionalMetaFields.value.map((field) => ({ key: field, label: META_LABELS[field] })),
    ...props.table.columns.map((column) => ({ key: column.key, label: `${column.label} (${column.role})` })),
]);

function isCurrent(row: ComparisonRow) {
    return Boolean(props.currentRunId) && row.run.id === props.currentRunId;
}

function display(column: ComparisonColumn): CellDisplay {
    return displayFor(column, props.table.rows, props.columnDisplay);
}

function setDisplay(column: ComparisonColumn, value: CellDisplay) {
    emit("update:columnDisplay", { ...props.columnDisplay, [column.key]: value });
}

const requestedMetadata = computed(() => props.table.query.metadata_elements ?? []);

// Column keys per run whose cells differ from the current run's.
const changed = computed(() => changedCells(props.table.rows, props.table.columns, display, props.currentRunId));

function isChanged(row: ComparisonRow, column: ComparisonColumn) {
    return Boolean(changed.value.get(row.run.id)?.has(column.key));
}

// Up to two runs picked for a side-by-side diff, by id so the choice survives transposing.
const MAX_SELECTED = 2;
const selectedRunIds = ref<string[]>([]);
const selectedSet = computed(() => new Set(selectedRunIds.value));
const diffOpen = ref(false);

/** Selecting past the limit drops the run selected first. */
function setSelected(runId: string, selected: boolean) {
    const others = selectedRunIds.value.filter((id) => id !== runId);
    selectedRunIds.value = selected ? [...others, runId].slice(-MAX_SELECTED) : others;
}

watch(
    () => props.table.rows,
    (rows) => {
        const onPage = new Set(rows.map((row) => row.run.id));
        selectedRunIds.value = selectedRunIds.value.filter((id) => onPage.has(id));
    },
);
watch(
    () => selectedRunIds.value.length,
    (count) => {
        if (count < MAX_SELECTED) {
            diffOpen.value = false;
        }
    },
);

const selectedIndices = computed(() =>
    props.table.rows.flatMap((row, index) => (selectedSet.value.has(row.run.id) ? [index] : [])),
);
const diffRows = computed(() => {
    const rows = props.table.rows.filter((row) => selectedSet.value.has(row.run.id));
    return diffOpen.value && rows.length === MAX_SELECTED ? (rows as [ComparisonRow, ComparisonRow]) : undefined;
});
const displays = computed(() => Object.fromEntries(props.table.columns.map((column) => [column.key, display(column)])));

/** Saves the page as shown: visible columns, each in its display, transposed or not. */
function exportPage(format: ExportFormat) {
    const lines = exportLines(props.table, {
        visibleColumns: props.visibleColumns,
        transpose: props.transpose,
        displayOf: display,
    });
    downloadBlob(exportBlob(lines, format), exportFilename(props.table.query, props.table.rows.length, format));
}

// Runs as rows.
const runFields = computed(() => [
    { key: "_expand", label: "" },
    { key: anchorField.value, label: META_LABELS[anchorField.value] },
    ...visibleMetaFields.value.map((field) => ({ key: field, label: META_LABELS[field] })),
    ...visibleDataColumns.value.map((column) => ({ key: keys.value[column.key]!, label: column.label })),
]);
const runItems = computed<RunItem[]>(() =>
    props.table.rows.map((row) => ({
        runId: row.run.id,
        row,
        current: isCurrent(row),
        class: isCurrent(row) ? "comparison-current-row" : undefined,
        cellClass: Object.fromEntries(
            [...(changed.value.get(row.run.id) ?? [])].map((key) => [keys.value[key]!, CHANGED_CLASS]),
        ),
    })),
);

// Runs as columns.
const lineFields = computed(() => [
    { key: "_line", label: "" },
    ...props.table.rows.map((row, index) => ({
        key: `r${index}`,
        label: "",
        cellClass: isCurrent(row) ? "comparison-current-cell" : undefined,
        headerClass: isCurrent(row) ? "comparison-current-cell" : undefined,
    })),
]);
const lineItems = computed<LineItem[]>(() => [
    ...visibleMetaFields.value.map((meta) => ({ lineKey: meta, meta })),
    ...visibleDataColumns.value.map((column) => ({
        lineKey: column.key,
        column,
        cellClass: Object.fromEntries(
            props.table.rows.flatMap((row, index) => (isChanged(row, column) ? [[`r${index}`, CHANGED_CLASS]] : [])),
        ),
    })),
]);

// GTable keeps expansion by index; remount it whenever the runs or the axes change.
const tableKey = computed(() => `${props.transpose}:${props.table.rows.map((row) => row.run.id).join(",")}`);
</script>

<template>
    <div class="comparison-table">
        <ListHeader
            list-id="comparison"
            :column-options="columnOptions"
            :visible-columns="visibleColumns"
            @toggle-column="emit('toggle-column', $event)"
            @reset-columns="emit('reset-columns')">
            <template v-slot:extra-filter>
                <slot name="toolbar" />
                <GButton
                    class="comparison-compare-selected"
                    size="small"
                    color="blue"
                    outline
                    :disabled="selectedRunIds.length < MAX_SELECTED"
                    disabled-title="Tick two runs to compare them side by side"
                    :aria-expanded="diffRows ? 'true' : 'false'"
                    :title="diffRows ? 'Hide the side-by-side comparison' : 'Show the selected runs side by side'"
                    @click="diffOpen = !diffOpen">
                    <FontAwesomeIcon :icon="faColumns" />
                    <template v-if="diffRows">Hide comparison</template>
                    <template v-else>Compare selected ({{ selectedRunIds.length }}/{{ MAX_SELECTED }})</template>
                </GButton>
                <GButton
                    class="comparison-transpose"
                    size="small"
                    color="blue"
                    outline
                    :pressed="transpose"
                    :aria-pressed="transpose ? 'true' : 'false'"
                    title="Show runs as columns"
                    @click="emit('update:transpose', !transpose)">
                    <FontAwesomeIcon :icon="faExchangeAlt" />
                    Transpose
                </GButton>
                <GDropdown
                    size="sm"
                    variant="outline-primary"
                    toggle-class="comparison-export"
                    :disabled="!table.rows.length"
                    title="Download this page as shown">
                    <template v-slot:button-content>
                        <FontAwesomeIcon :icon="faDownload" />
                        Export
                    </template>
                    <GDropdownItem class="comparison-export-csv" @click="exportPage('csv')">CSV</GDropdownItem>
                    <GDropdownItem class="comparison-export-tsv" @click="exportPage('tsv')">TSV</GDropdownItem>
                </GDropdown>
            </template>
        </ListHeader>

        <ComparisonDiff
            v-if="diffRows"
            :rows="diffRows"
            :columns="table.columns"
            :query="table.query"
            :displays="displays"
            :current-run-id="currentRunId"
            :requested-metadata="requestedMetadata"
            :loading="loading"
            @close="diffOpen = false" />

        <GAlert v-if="!table.rows.length && !loading" class="comparison-empty" variant="info" show>
            {{ emptyMessage }}
        </GAlert>

        <div v-else class="comparison-table-scroll">
            <GTable
                v-if="!transpose"
                :key="tableKey"
                :fields="runFields"
                :items="runItems"
                primary-key="runId"
                selectable
                no-select-on-click
                :selected-items="selectedIndices"
                select-checkbox-title="Select to compare"
                :local-sorting="false"
                :local-filtering="false"
                :striped="false"
                :overlay-loading="loading"
                compact
                @row-select="setSelected($event.item.runId, $event.selected)">
                <template v-slot:cell(_expand)="{ detailsShowing, toggleDetails }">
                    <GButton
                        class="comparison-expand"
                        transparent
                        icon-only
                        size="small"
                        :aria-expanded="detailsShowing ? 'true' : 'false'"
                        :aria-label="detailsShowing ? 'Hide run details' : 'Show run details'"
                        :title="detailsShowing ? 'Hide run details' : 'Show run details'"
                        @click="toggleDetails">
                        <FontAwesomeIcon :icon="detailsShowing ? faAngleDown : faAngleRight" fixed-width />
                    </GButton>
                </template>
                <template
                    v-for="field in [anchorField, ...visibleMetaFields]"
                    :key="field"
                    v-slot:[`cell(${field})`]="{ item }">
                    <ComparisonMetaCell :field="field" :row="item.row" :query="table.query" :current="item.current" />
                </template>
                <template
                    v-for="column in visibleDataColumns"
                    :key="`h-${column.key}`"
                    v-slot:[`head(${keys[column.key]})`]>
                    <ComparisonColumnHeader
                        :column="column"
                        :rows="table.rows"
                        :display="display(column)"
                        @update:display="setDisplay(column, $event)" />
                </template>
                <template
                    v-for="column in visibleDataColumns"
                    :key="`c-${column.key}`"
                    v-slot:[`cell(${keys[column.key]})`]="{ item }">
                    <span :title="isChanged(item.row, column) ? CHANGED_TITLE : undefined">
                        <ComparisonCell
                            :cell="item.row.cells[column.key]"
                            :row="item.row"
                            :display="display(column)"
                            :requested-metadata="requestedMetadata"
                            :loading="loading" />
                    </span>
                </template>
                <template v-slot:row-details="{ item }">
                    <ComparisonRowDetail :row="item.row" :columns="table.columns" :query="table.query" />
                </template>
            </GTable>

            <GTable
                v-else
                :key="tableKey"
                :fields="lineFields"
                :items="lineItems"
                primary-key="lineKey"
                :local-sorting="false"
                :local-filtering="false"
                :striped="false"
                :overlay-loading="loading"
                compact>
                <template v-for="(row, index) in table.rows" :key="`h-${row.run.id}`" v-slot:[`head(r${index})`]>
                    <GCheckbox
                        class="comparison-select-run d-inline-block mr-1"
                        :model-value="selectedSet.has(row.run.id)"
                        aria-label="Select to compare"
                        title="Select to compare"
                        @update:model-value="setSelected(row.run.id, $event)" />
                    <ComparisonMetaCell
                        :field="anchorField"
                        :row="row"
                        :query="table.query"
                        :current="isCurrent(row)" />
                </template>
                <template v-slot:cell(_line)="{ item }">
                    <ComparisonColumnHeader
                        v-if="item.column"
                        :column="item.column"
                        :rows="table.rows"
                        :display="display(item.column)"
                        @update:display="setDisplay(item.column, $event)" />
                    <span v-else class="font-weight-bold">{{ META_LABELS[item.meta as MetaField] }}</span>
                </template>
                <template
                    v-for="(row, index) in table.rows"
                    :key="`c-${row.run.id}`"
                    v-slot:[`cell(r${index})`]="{ item }">
                    <span v-if="item.column" :title="isChanged(row, item.column) ? CHANGED_TITLE : undefined">
                        <ComparisonCell
                            :cell="row.cells[item.column.key]"
                            :row="row"
                            :display="display(item.column)"
                            :requested-metadata="requestedMetadata"
                            :loading="loading" />
                    </span>
                    <ComparisonMetaCell
                        v-else
                        :field="item.meta!"
                        :row="row"
                        :query="table.query"
                        :current="isCurrent(row)" />
                </template>
            </GTable>
        </div>
    </div>
</template>

<style scoped lang="scss">
.comparison-table-scroll {
    overflow-x: auto;

    :deep(td),
    :deep(th) {
        white-space: nowrap;
        vertical-align: middle;
    }
    :deep(.g-table-details-row td) {
        white-space: normal;
        background: var(--color-grey-100);
    }
    :deep(.comparison-current-row > td),
    :deep(.comparison-current-cell) {
        background: var(--color-blue-100);
    }
    :deep(td.comparison-cell-changed) {
        background: var(--color-yellow-200);
        box-shadow: inset 3px 0 0 var(--color-yellow-600);
    }
}
</style>
