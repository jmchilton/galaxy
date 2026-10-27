<script setup lang="ts">
import type { ComparisonColumn, ComparisonRow } from "@/api/comparisons";

import type { CellDisplay } from "./comparisonUtils";

import ComparisonCell from "./cells/ComparisonCell.vue";

withDefaults(
    defineProps<{
        row: ComparisonRow;
        column: ComparisonColumn;
        display: CellDisplay;
        /** Whether the cell differs from the viewed run's. */
        changed?: boolean;
        requestedMetadata?: string[];
        loading?: boolean;
    }>(),
    { changed: false, requestedMetadata: () => [], loading: false },
);
</script>

<template>
    <span :title="changed ? 'Differs from the run you are viewing' : undefined">
        <ComparisonCell
            :cell="row.cells[column.key]"
            :row="row"
            :display="display"
            :role="column.role"
            :requested-metadata="requestedMetadata"
            :loading="loading" />
    </span>
</template>
