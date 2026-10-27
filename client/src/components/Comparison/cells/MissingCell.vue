<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonRow, MissingCell } from "@/api/comparisons";

import { MISSING_TITLES, missingText } from "../comparisonTable";

const props = defineProps<{
    cell: MissingCell;
    row: Pick<ComparisonRow, "version" | "tool_version">;
}>();

const text = computed(() => missingText(props.cell, props.row));
</script>

<template>
    <span class="comparison-missing" :class="`comparison-missing-${cell.reason}`" :title="MISSING_TITLES[cell.reason]">
        <span aria-hidden="true">&mdash;</span>
        <span class="badge badge-light font-weight-normal">{{ text }}</span>
    </span>
</template>

<style scoped>
.comparison-missing {
    color: var(--color-grey-600);
    font-style: italic;
}
</style>
