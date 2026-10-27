import { describe, expect, it } from "vitest";
import { nextTick, ref } from "vue";

import type { ComparisonRow } from "@/api/comparisons";

import { STEP_RUNS_TABLE } from "./test-utils";
import { useRunSelection } from "./useRunSelection";

const ROWS = STEP_RUNS_TABLE.rows;

function ids(rows: ComparisonRow[] | undefined) {
    return rows?.map((row) => row.run.id);
}

describe("useRunSelection", () => {
    it("keeps the two most recently selected runs, in table order for the diff", () => {
        const { selectedRunIds, selectedIndices, diffOpen, diffRows, setSelected } = useRunSelection(ref(ROWS));
        setSelected(ROWS[2]!.run.id, true);
        setSelected(ROWS[0]!.run.id, true);
        setSelected(ROWS[1]!.run.id, true);
        expect(selectedRunIds.value).toEqual([ROWS[0]!.run.id, ROWS[1]!.run.id]);
        expect(selectedIndices.value).toEqual([0, 1]);
        expect(diffRows.value).toBeUndefined();
        diffOpen.value = true;
        expect(ids(diffRows.value)).toEqual([ROWS[0]!.run.id, ROWS[1]!.run.id]);
    });

    it("closes the diff when a run is deselected", async () => {
        const { diffOpen, diffRows, setSelected } = useRunSelection(ref(ROWS));
        setSelected(ROWS[0]!.run.id, true);
        setSelected(ROWS[1]!.run.id, true);
        diffOpen.value = true;
        setSelected(ROWS[1]!.run.id, false);
        await nextTick();
        expect(diffOpen.value).toBe(false);
        expect(diffRows.value).toBeUndefined();
    });

    it("drops selected runs that leave the page", async () => {
        const rows = ref(ROWS);
        const { selectedRunIds, setSelected } = useRunSelection(rows);
        setSelected(ROWS[0]!.run.id, true);
        setSelected(ROWS[1]!.run.id, true);
        rows.value = ROWS.slice(1);
        await nextTick();
        expect(selectedRunIds.value).toEqual([ROWS[1]!.run.id]);
    });
});
