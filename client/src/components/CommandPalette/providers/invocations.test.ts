import { deferred } from "@tests/vitest/deferred";
import flushPromises from "flush-promises";
import { createPinia, disposePinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import type { WorkflowInvocationCollectionView } from "@/api/invocations";
import { getData as getInvocationsData } from "@/components/Grid/configs/invocations";
import type { RecentPaletteItem } from "@/composables/useRecentPaletteItems";
import { useInvocationStore } from "@/stores/invocationStore";

import { makeCtx } from "../test-utils";
import { PaletteFetchError } from "./errors";
import { invocationsProvider } from "./invocations";
import { resetListRefreshTracking } from "./refresh";
import type { ScopeDefinition } from "./scopes";

vi.mock("@/components/Grid/configs/invocations", () => ({
    getData: vi.fn(),
}));

const WORKFLOW_NAMES: Record<string, string> = { wf1: "Variant calling", wf2: "RNA-seq" };
const HISTORY_NAMES: Record<string, string> = { h1: "My analysis", h2: "Scratch" };

// awaited by the provider so the names are there to render
const fetchWorkflowForInstanceIdCached = vi.fn(async (_id: string): Promise<void> => undefined);
const loadHistoryById = vi.fn(async (_id: string): Promise<void> => undefined);

vi.mock("@/stores/workflowStore", () => ({
    useWorkflowStore: () => ({
        getStoredWorkflowNameByInstanceId: (id: string, fallback = "...") => WORKFLOW_NAMES[id] ?? fallback,
        fetchWorkflowForInstanceIdCached,
    }),
}));

vi.mock("@/stores/historyStore", () => ({
    useHistoryStore: () => ({
        getHistoryById: (id: string) => (HISTORY_NAMES[id] ? { id, name: HISTORY_NAMES[id] } : null),
        loadHistoryById,
    }),
}));

const recentItems = vi.fn<() => RecentPaletteItem[]>(() => []);

vi.mock("@/composables/useRecentPaletteItems", () => ({
    useRecentPaletteItems: () => ({ recentItems, addRecentItem: vi.fn(), clearRecentItems: vi.fn() }),
}));

const INVOCATIONS: Omit<WorkflowInvocationCollectionView, "model_class">[] = [
    {
        id: "inv1",
        workflow_id: "wf1",
        history_id: "h1",
        state: "scheduled",
        create_time: "2026-08-30T10:00:00",
        update_time: "2026-08-30T10:00:00",
    },
    {
        id: "inv2",
        workflow_id: "wf2",
        history_id: "h2",
        state: "new",
        create_time: "2026-08-29T10:00:00",
        update_time: "2026-08-29T10:00:00",
    },
    {
        id: "inv3",
        workflow_id: "unknown_wf",
        history_id: "unknown_history",
        state: "cancelled",
        create_time: "2026-08-28T10:00:00",
        update_time: "2026-08-28T10:00:00",
    },
];

const SCOPE: ScopeDefinition = { key: "i", label: "Invocations", providerId: "invocations" };

const searchScopedInvocations = invocationsProvider.searchScoped;
if (!searchScopedInvocations) {
    throw new Error("Invocations must support scoped search");
}
const emptyQueryItems = invocationsProvider.emptyQueryItems;
if (!emptyQueryItems) {
    throw new Error("Invocations must expose their cached empty-query items");
}

let pinia: ReturnType<typeof createPinia>;

describe("invocationsProvider", () => {
    beforeEach(() => {
        const ownedPinia = createPinia();
        pinia = ownedPinia;
        setActivePinia(ownedPinia);
        onTestFinished(async () => {
            await flushPromises();
            disposePinia(ownedPinia);
            resetListRefreshTracking();
        });
        recentItems.mockReturnValue([]);
        resetListRefreshTracking();
        fetchWorkflowForInstanceIdCached.mockReset().mockResolvedValue(undefined);
        loadHistoryById.mockClear();
        vi.mocked(getInvocationsData).mockReset();
        // Keep the original list rows partial: model_class is not consumed by these palette scenarios.
        vi.mocked(getInvocationsData).mockResolvedValue([
            INVOCATIONS as WorkflowInvocationCollectionView[],
            INVOCATIONS.length,
        ]);
    });

    it("maps invocations to items with workflow, state, date and history", async () => {
        const sections = await searchScopedInvocations(SCOPE, "variant", makeCtx());
        const items = sections[0]?.items ?? [];
        expect(items).toHaveLength(1);
        expect(items[0]?.id).toBe("invocations:inv1");
        expect(items[0]?.title).toBe("Variant calling");
        expect(items[0]?.subtitle).toContain("scheduled");
        expect(items[0]?.subtitle).toContain("2026");
        expect(items[0]?.subtitle).toContain("My analysis");
        expect(items[0]?.to).toBe("/workflows/invocations/inv1");
    });

    it("resolves the workflow and history names before it settles", async () => {
        const workflowLookup = deferred<void>();
        fetchWorkflowForInstanceIdCached.mockImplementationOnce(() => workflowLookup.promise);
        let settled = false;
        const search = Promise.resolve(searchScopedInvocations(SCOPE, "", makeCtx())).then(() => (settled = true));
        try {
            await flushPromises();

            // `getData` only starts these lookups; the provider awaits them so fresh rows show names
            expect(settled).toBe(false);
            expect(fetchWorkflowForInstanceIdCached.mock.calls.map(([id]) => id)).toEqual(["wf1", "wf2", "unknown_wf"]);
            // cached histories are not looked up again
            expect(loadHistoryById.mock.calls.map(([id]) => id)).toEqual(["unknown_history"]);

            workflowLookup.resolve();
            await search;
            expect(settled).toBe(true);
        } finally {
            workflowLookup.resolve();
            await search;
        }
    });

    it("falls back to the invocation id when the workflow name is unknown", async () => {
        const sections = await searchScopedInvocations(SCOPE, "", makeCtx());
        const latest = sections?.find((s) => s.id === "latest");
        expect(latest?.items.map((i) => i.title)).toEqual(["Variant calling", "RNA-seq", "Invocation inv3"]);
    });

    it("filters client-side by history name too", async () => {
        const sections = await searchScopedInvocations(SCOPE, "scratch", makeCtx());
        expect(sections[0]?.items.map((i) => i.id)).toEqual(["invocations:inv2"]);
    });

    it("filters the cache in the unscoped fan-out and never fetches there", async () => {
        // nothing cached yet: the fan-out contributes nothing rather than fetching
        expect(await invocationsProvider.search("variant", makeCtx())).toEqual([]);
        expect(getInvocationsData).not.toHaveBeenCalled();

        await useInvocationStore(pinia).fetchLatestInvocations(15);
        vi.mocked(getInvocationsData).mockClear();

        const items = await invocationsProvider.search("variant", makeCtx());

        expect(items.map((i) => i.id)).toEqual(["invocations:inv1"]);
        expect(getInvocationsData).not.toHaveBeenCalled();
    });

    it("renders the store cache without fetching again", async () => {
        const invocationStore = useInvocationStore(pinia);
        await invocationStore.fetchLatestInvocations(15);
        vi.mocked(getInvocationsData).mockClear();

        const items = emptyQueryItems(makeCtx());
        expect(items.map((i) => i.id)).toEqual(["invocations:inv1", "invocations:inv2", "invocations:inv3"]);
        expect(getInvocationsData).not.toHaveBeenCalled();
    });

    it("shows remembered invocations above the latest ones", async () => {
        recentItems.mockReturnValue([{ type: "invocation", id: "inv2", name: "RNA-seq" }]);
        const sections = await searchScopedInvocations(SCOPE, "", makeCtx());
        expect(sections.map((s) => s.id)).toEqual(["recent", "latest"]);
        expect(sections[0]?.items.map((i) => i.id)).toEqual(["invocations:inv2"]);
        expect(sections[1]?.items.map((i) => i.id)).toEqual(["invocations:inv1", "invocations:inv3"]);
    });

    it("fetches once and answers further keystrokes from the store", async () => {
        await searchScopedInvocations(SCOPE, "", makeCtx());
        expect(getInvocationsData).toHaveBeenCalledTimes(1);

        // the invocations index has no free-text search, so a query must not
        // repeat the identical unfiltered request
        await searchScopedInvocations(SCOPE, "r", makeCtx());
        await searchScopedInvocations(SCOPE, "rn", makeCtx());
        await searchScopedInvocations(SCOPE, "rna", makeCtx());

        expect(getInvocationsData).toHaveBeenCalledTimes(1);
    });

    it("does not refetch for a user without invocations", async () => {
        vi.mocked(getInvocationsData).mockResolvedValue([[], 0]);

        await searchScopedInvocations(SCOPE, "", makeCtx());
        await searchScopedInvocations(SCOPE, "rna", makeCtx());

        expect(getInvocationsData).toHaveBeenCalledTimes(1);
    });

    it("refreshes the cached list in the background once it goes stale", async () => {
        await searchScopedInvocations(SCOPE, "", makeCtx());
        expect(getInvocationsData).toHaveBeenCalledTimes(1);

        resetListRefreshTracking();
        fetchWorkflowForInstanceIdCached.mockClear();
        const sections = await searchScopedInvocations(SCOPE, "", makeCtx());

        expect(sections.at(-1)?.items.map((i) => i.id)).toEqual([
            "invocations:inv1",
            "invocations:inv2",
            "invocations:inv3",
        ]);
        expect(getInvocationsData).toHaveBeenCalledTimes(2);
        // the refreshed rows resolve their names as well
        await flushPromises();
        expect(fetchWorkflowForInstanceIdCached).toHaveBeenCalledTimes(3);
    });

    it("keeps rendering the cached invocations when a fetch fails", async () => {
        await searchScopedInvocations(SCOPE, "", makeCtx());
        vi.mocked(getInvocationsData).mockRejectedValue(new Error("boom"));
        resetListRefreshTracking();

        const sections = await searchScopedInvocations(SCOPE, "rna", makeCtx());

        expect(sections[0]?.items.map((i) => i.id)).toEqual(["invocations:inv2"]);
    });

    it("reports a failed first fetch and retries it on the next search", async () => {
        vi.mocked(getInvocationsData).mockRejectedValueOnce(new Error("boom"));

        await expect(searchScopedInvocations(SCOPE, "", makeCtx())).rejects.toBeInstanceOf(PaletteFetchError);

        const sections = await searchScopedInvocations(SCOPE, "", makeCtx());
        expect(sections.at(-1)?.items.map((i) => i.id)).toEqual(INVOCATIONS.map((i) => `invocations:${i.id}`));
    });

    it("returns a single results section for a scoped query", async () => {
        const sections = await searchScopedInvocations(SCOPE, "rna", makeCtx());
        expect(sections).toHaveLength(1);
        expect(sections[0]?.id).toBe("results");
        expect(sections[0]?.items.map((i) => i.id)).toEqual(["invocations:inv2"]);
    });
});
