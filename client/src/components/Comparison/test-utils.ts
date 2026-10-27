import type { ComparisonTable } from "@/api/comparisons";
import { useHashedUserId } from "@/composables/hashedUserIdFromUserStore";

import STEP_RUNS from "./test-data/step_runs.json";

/** A recorded step_runs response: not run yet, plain v2 and v1 runs, a mapped batch, a deleted history. */
export const STEP_RUNS_TABLE = STEP_RUNS as unknown as ComparisonTable;

export const ITEM_LINK_STUB = {
    name: "ItemPopoverLink",
    props: ["itemId", "itemSrc", "to", "linkClass"],
    template: "<a class='item-link'><slot /></a>",
};

export const JOB_PARAMETERS_DIFF_STUB = {
    name: "JobParametersDiff",
    props: ["jobIdA", "jobIdB", "labelA", "labelB", "onlyDifferences"],
    template: "<div />",
};

/** Local storage key of the current user's comparison display preferences. */
export function displayPrefsKey(): string {
    return `comparison-display-${useHashedUserId().hashedUserId.value}`;
}

export function seedDisplayPrefs(prefs: Record<string, unknown>): void {
    localStorage.setItem(displayPrefsKey(), JSON.stringify(prefs));
}
