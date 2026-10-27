<script setup lang="ts">
import { BPagination } from "bootstrap-vue";
import { computed } from "vue";

const props = defineProps<{
    /** Runs matching the query, from `total_matches`. */
    total: number;
    limit: number;
    /** The page asked for. */
    offset: number;
    /** Offset of the loaded rows, which the summary describes while the next page loads. */
    loadedOffset: number;
    /** Runs on the loaded page. */
    rowCount: number;
}>();

const emit = defineEmits<{
    (e: "update:offset", value: number): void;
}>();

const page = computed({
    get: () => Math.floor(props.offset / props.limit) + 1,
    set: (value: number) => emit("update:offset", (value - 1) * props.limit),
});

const summary = computed(() => {
    if (!props.rowCount) {
        return "";
    }
    const firstRow = props.loadedOffset + 1;
    return `Showing ${firstRow}–${firstRow + props.rowCount - 1} of ${props.total} · newest first · your runs only`;
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
