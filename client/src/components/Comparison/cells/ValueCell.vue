<script setup lang="ts">
import { computed } from "vue";

import { formatValue, isScalar } from "../comparisonUtils";

const props = defineProps<{
    value: unknown;
}>();

const text = computed(() => formatValue(props.value));
const scalar = computed(() => isScalar(props.value));
const valueClass = computed(() => {
    if (props.value === null || props.value === undefined) {
        return "comparison-value-null";
    }
    return `comparison-value-${typeof props.value}`;
});
</script>

<template>
    <code v-if="scalar" class="comparison-value" :class="valueClass">{{ text }}</code>
    <pre v-else class="comparison-value comparison-value-json mb-0">{{ text }}</pre>
</template>

<style scoped>
.comparison-value {
    color: inherit;
    background: var(--color-grey-100);
    border: 1px solid var(--color-grey-200);
    border-radius: 3px;
    padding: 0 0.3rem;
}
.comparison-value-null {
    color: var(--color-grey-600);
    font-style: italic;
}
.comparison-value-json {
    max-height: 12rem;
    max-width: 24rem;
    overflow: auto;
    font-size: 0.8rem;
}
</style>
