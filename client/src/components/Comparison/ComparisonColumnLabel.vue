<script setup lang="ts">
import type { ComparisonColumn } from "@/api/comparisons";

import { ROLE_LABELS } from "./comparisonUtils";

defineProps<{
    column: Pick<ComparisonColumn, "role" | "label">;
}>();
</script>

<template>
    <span class="d-inline-flex align-items-center">
        <span class="comparison-role badge" :class="`comparison-role-${column.role}`" :title="column.role">
            {{ ROLE_LABELS[column.role] }}
        </span>
        <code class="comparison-column-label">{{ column.label }}</code>
    </span>
</template>

<style scoped lang="scss">
.comparison-role {
    font-size: 0.65rem;
    text-transform: uppercase;
    border: 1px solid currentColor;
    margin-right: 0.3rem;
}
.comparison-role-input {
    color: var(--color-blue-600);
}
.comparison-role-output {
    color: var(--color-green-700);
}
.comparison-role-parameter {
    color: var(--color-orange-700);
}
.comparison-column-label {
    color: inherit;
}
</style>
