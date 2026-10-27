import { createTestingPinia } from "@pinia/testing";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EffectScope, effectScope, ref } from "vue";

import type { ComparisonResult, ComparisonTable } from "@/api/comparisons";
import { useHashedUserId } from "@/composables/hashedUserIdFromUserStore";

import STEP_RUNS from "./test-data/step_runs.json";
import { MAX_STORED_DISPLAYS, useComparisonDisplay, useComparisonFetch } from "./useComparison";

const TABLE = STEP_RUNS as unknown as ComparisonTable;

vi.unmock("@/composables/userLocalStorage");

let scope: EffectScope;

beforeEach(() => {
    localStorage.clear();
    setActivePinia(createTestingPinia({ createSpy: vi.fn, stubActions: false }));
    scope = effectScope();
});

afterEach(() => {
    scope.stop();
});

describe("useComparisonFetch", () => {
    it("fetches the same params again after a failure", async () => {
        const fetcher = vi
            .fn<(params: { offset: number }) => Promise<ComparisonResult>>()
            .mockRejectedValueOnce(new Error("Server down"))
            .mockResolvedValue({ table: TABLE, total: 6 });
        const params = ref({ offset: 0 });
        const { error, table } = scope.run(() => useComparisonFetch(params, fetcher))!;
        await flushPromises();
        expect(error.value).toBe("Server down");
        params.value = { offset: 0 };
        await flushPromises();
        expect(fetcher).toHaveBeenCalledTimes(2);
        expect(error.value).toBeUndefined();
        expect(table.value).toEqual(TABLE);
    });
});

describe("useComparisonDisplay", () => {
    function storageKey() {
        return `comparison-display-${useHashedUserId().hashedUserId.value}`;
    }

    it("keeps only the most recently changed comparisons", async () => {
        const seeded = Object.fromEntries(
            Array.from({ length: MAX_STORED_DISPLAYS }, (_, i) => [`k${i}`, { transpose: true }]),
        );
        localStorage.setItem(storageKey(), JSON.stringify(seeded));
        const key = ref("k0");
        const display = scope.run(() => useComparisonDisplay(key, ref(TABLE)))!;
        display.transpose.value = false;
        key.value = "new";
        display.transpose.value = true;
        await flushPromises();
        const stored = JSON.parse(localStorage.getItem(storageKey())!);
        const keys = Object.keys(stored);
        expect(keys).toHaveLength(MAX_STORED_DISPLAYS);
        expect(keys.slice(-2)).toEqual(["k0", "new"]);
        expect(keys).not.toContain("k1");
        expect(stored.k0).toEqual({ transpose: false });
    });
});
