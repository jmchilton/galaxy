import { computed, type Ref, ref, watch } from "vue";

import type { ComparisonRow } from "@/api/comparisons";

/** Runs a side-by-side diff compares. */
export const MAX_SELECTED = 2;

/** Up to two runs picked for a side-by-side diff, by id so the choice survives transposing; only runs on the page. */
export function useRunSelection(rows: Ref<ComparisonRow[]>) {
    const selectedRunIds = ref<string[]>([]);
    const selectedSet = computed(() => new Set(selectedRunIds.value));
    const diffOpen = ref(false);

    /** Selecting past the limit drops the run selected first. */
    function setSelected(runId: string, selected: boolean) {
        const others = selectedRunIds.value.filter((id) => id !== runId);
        selectedRunIds.value = selected ? [...others, runId].slice(-MAX_SELECTED) : others;
    }

    watch(rows, (current) => {
        const onPage = new Set(current.map((row) => row.run.id));
        selectedRunIds.value = selectedRunIds.value.filter((id) => onPage.has(id));
    });
    watch(
        () => selectedRunIds.value.length,
        (count) => {
            if (count < MAX_SELECTED) {
                diffOpen.value = false;
            }
        },
    );

    const selectedIndices = computed(() =>
        rows.value.flatMap((row, index) => (selectedSet.value.has(row.run.id) ? [index] : [])),
    );
    /** The selected runs in table order, while the diff is open. */
    const diffRows = computed(() => {
        const selected = rows.value.filter((row) => selectedSet.value.has(row.run.id));
        return diffOpen.value && selected.length === MAX_SELECTED
            ? (selected as [ComparisonRow, ComparisonRow])
            : undefined;
    });

    return { selectedRunIds, selectedSet, selectedIndices, diffOpen, diffRows, setSelected };
}
