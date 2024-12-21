<script setup lang="ts">
import { type ColDef } from "ag-grid-community";
import { BCol, BContainer, BRow } from "bootstrap-vue";
import { computed, ref } from "vue";

import type { HistoryItemSummary } from "@/api";
import { useAgGrid } from "@/composables/useAgGrid";

import type { DatasetPair } from "../History/adapters/buildCollectionModal";

interface Props {
    historyId: string;
    initialElements: HistoryItemSummary[];
    defaultHideSourceItems?: boolean;
    fromSelection?: boolean;
    extensions?: string[];
    height?: string;
    width?: string;
}

const { gridApi, AgGridVue, onGridReady, theme } = useAgGrid(resize);

const generatedPairs = ref<DatasetPair[]>([]);

function resize() {
    if (gridApi.value) {
        gridApi.value.sizeColumnsToFit();
    }
}

const props = defineProps<Props>();

const style = computed(() => {
    return { width: props.width || "100%", height: props.height || "500px" };
});

// Default Column Properties
const defaultColDef = ref<ColDef>({
    editable: false,
    sortable: false,
    filter: false,
    resizable: true,
});

const rowData = ref<Record<string, unknown>[]>([]);

const columnDefs = computed(() => {
    const datasets: ColDef = {
        headerName: "Dataset(s)",
        field: "datasets",
        editable: false,
    };
    return [datasets];
});

const summaryText = computed(() => {
    const numMatchedText = `Auto-matched ${generatedPairs.value.length} pair(s) of datasets from target datasets.`;
    const numUnmatched = props.initialElements.length;
    let numUnmatchedText = "";
    if (numUnmatched > 0) {
        numUnmatchedText = `${numUnmatched} dataset(s) were not paired and will not be included in the resulting list of pairs.`;
    }
    return `${numMatchedText} ${numUnmatchedText}`;
});

function initialize() {
    for (const dataset of props.initialElements) {
        console.log(dataset);
        rowData.value.push({ datasets: dataset.name });
    }
}

initialize();
</script>

<template>
    <BContainer style="max-width: 100%">
        <BRow>
            <BCol>
                <p>{{ summaryText }}</p>
            </BCol>
        </BRow>
        <BRow>
            <div :style="style" :class="theme">
                <AgGridVue
                    :row-data="rowData"
                    :column-defs="columnDefs"
                    :default-col-def="defaultColDef"
                    :style="style"
                    @gridReady="onGridReady" />
            </div>
        </BRow>
    </BContainer>
</template>
