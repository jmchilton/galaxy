import { createTestingPinia } from "@pinia/testing";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type EffectScope, effectScope, ref } from "vue";

import type { ComparisonResult } from "@/api/comparisons";

import { displayPrefsKey, seedDisplayPrefs, STEP_RUNS_TABLE } from "./test-utils";
import { MAX_STORED_DISPLAYS, useComparisonDisplay, useComparisonFetch } from "./useComparison";

const TABLE = STEP_RUNS_TABLE;

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
    it("keeps only the most recently changed comparisons", async () => {
        const seeded = Object.fromEntries(
            Array.from({ length: MAX_STORED_DISPLAYS }, (_, i) => [`k${i}`, { transpose: true }]),
        );
        seedDisplayPrefs(seeded);
        const key = ref("k0");
        const display = scope.run(() => useComparisonDisplay(key, ref(TABLE)))!;
        display.transpose.value = false;
        key.value = "new";
        display.transpose.value = true;
        await flushPromises();
        const stored = JSON.parse(localStorage.getItem(displayPrefsKey())!);
        const keys = Object.keys(stored);
        expect(keys).toHaveLength(MAX_STORED_DISPLAYS);
        expect(keys.slice(-2)).toEqual(["k0", "new"]);
        expect(keys).not.toContain("k1");
        expect(stored.k0).toEqual({ transpose: false });
    });
});
