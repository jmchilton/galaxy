<script setup lang="ts">
import { computed } from "vue";

import type { ComparisonColumn, ComparisonRow, MissingCell } from "@/api/comparisons";

import { missingText, missingTitle } from "../comparisonUtils";

const props = defineProps<{
    cell: MissingCell;
    row: Pick<ComparisonRow, "version" | "tool_version">;
    role?: ComparisonColumn["role"];
}>();

const text = computed(() => missingText(props.cell, props.row, props.role));
const title = computed(() => missingTitle(props.cell, props.role));
</script>

<template>
    <span class="comparison-missing" :class="`comparison-missing-${cell.reason}`" :title="title">
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
