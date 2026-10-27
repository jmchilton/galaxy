<script setup lang="ts">
import { computed } from "vue";

import type { CollectionCell, DatasetCell } from "@/api/comparisons";

import ValueCell from "./ValueCell.vue";

const props = defineProps<{
    cell: DatasetCell | CollectionCell;
    element: string;
    /** Whether the loaded table asked the server for this element. */
    requested: boolean;
}>();

const isSet = computed(
    () =>
        props.cell.type === "dataset" &&
        props.cell.metadata[props.element] !== undefined &&
        props.cell.metadata[props.element] !== null,
);
</script>

<template>
    <span
        v-if="cell.type === 'collection'"
        class="comparison-metadata-na text-muted"
        title="Collections have no dataset metadata">
        {{ cell.collection_type }} &middot; {{ cell.element_count ?? "?" }}
    </span>
    <span v-else-if="!requested" class="comparison-metadata-loading text-muted">loading&hellip;</span>
    <ValueCell v-else-if="isSet" :value="cell.metadata[element]" />
    <span v-else class="comparison-metadata-unset text-muted font-italic" title="Not set for this dataset"
        >not set</span
    >
</template>
