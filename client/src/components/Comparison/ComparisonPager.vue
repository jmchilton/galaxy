<script setup lang="ts">
import { BPagination } from "bootstrap-vue";
import { computed } from "vue";

import type { ComparisonSortBy, ComparisonTable } from "@/api/comparisons";

const SORT_ORDER: Record<ComparisonSortBy, [descending: string, ascending: string]> = {
    create_time: ["newest first", "oldest first"],
    update_time: ["recently updated first", "least recently updated first"],
};

const props = defineProps<{
    /** The loaded page, which the summary describes while the next page loads. */
    table: ComparisonTable;
    /** Runs matching the query, from `total_matches`. */
    total: number;
    limit: number;
    /** The page asked for. */
    offset: number;
}>();

const emit = defineEmits<{
    (e: "update:offset", value: number): void;
}>();

const page = computed({
    get: () => Math.floor(props.offset / props.limit) + 1,
    set: (value: number) => emit("update:offset", (value - 1) * props.limit),
});

const summary = computed(() => {
    const { query, rows } = props.table;
    if (!rows.length) {
        return "";
    }
    const firstRow = query.offset + 1;
    const order = SORT_ORDER[query.sort_by ?? "create_time"][(query.sort_desc ?? true) ? 0 : 1];
    return `Showing ${firstRow}–${firstRow + rows.length - 1} of ${props.total} · ${order} · your runs only`;
});
</script>

<template>
    <div class="comparison-pager d-flex flex-wrap justify-content-between align-items-center mt-2">
        <small class="comparison-summary text-muted">{{ summary }}</small>
        <div class="d-flex align-items-center flex-gapx-1">
            <slot />
            <BPagination
                v-if="total > limit"
                v-model="page"
                :total-rows="total"
                :per-page="limit"
                size="sm"
                class="mb-0"
                aria-label="Pages of runs" />
        </div>
    </div>
</template>
