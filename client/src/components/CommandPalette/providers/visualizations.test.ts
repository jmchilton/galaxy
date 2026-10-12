import { getFakeVisualizationSummary } from "@tests/test-data/visualizations";
import flushPromises from "flush-promises";
import { createPinia, disposePinia, setActivePinia } from "pinia";
import MockDate from "timezone-mock";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { loadVisualizations, type VisualizationSummary } from "@/api/visualizations";
import type { RecentPaletteItem } from "@/composables/useRecentPaletteItems";
import { useVisualizationStore } from "@/stores/visualizationStore";

import { makeCtx, renderedSections } from "../test-utils";
import { resetListRefreshTracking } from "./refresh";
import type { ScopeDefinition } from "./scopes";
import { visualizationsProvider } from "./visualizations";

vi.mock("@/api/visualizations", () => ({
    loadVisualizations: vi.fn(),
}));

const recentEntries: RecentPaletteItem[] = [];

vi.mock("@/composables/useRecentPaletteItems", () => ({
    useRecentPaletteItems: () => ({
        recentItems: (type: string) => recentEntries.filter((entry) => entry.type === type),
        addRecentItem: vi.fn(),
        clearRecentItems: vi.fn(),
    }),
}));

const VISUALIZATION_SCOPE: ScopeDefinition = { key: "v", label: "Visualizations", providerId: "visualizations" };

function respondWithList(...visualizations: VisualizationSummary[]) {
    vi.mocked(loadVisualizations).mockResolvedValue({ data: visualizations, totalMatches: visualizations.length });
}

const searchScopedVisualizations = visualizationsProvider.searchScoped;
if (!searchScopedVisualizations) {
    throw new Error("Visualizations must support scoped search");
}
const emptyQueryItems = visualizationsProvider.emptyQueryItems;
if (!emptyQueryItems) {
    throw new Error("Visualizations must expose their cached empty-query items");
}

let pinia: ReturnType<typeof createPinia>;

describe("visualizationsProvider", () => {
    beforeEach(() => {
        // subtitles carry a date formatted in local time, so the zone is pinned
        // the way utils/dates.test.ts pins it
        onTestFinished(() => {
            MockDate.unregister();
        });
        MockDate.register("Etc/GMT+4");
        const ownedPinia = createPinia();
        pinia = ownedPinia;
        setActivePinia(ownedPinia);
        onTestFinished(async () => {
            await flushPromises();
            disposePinia(ownedPinia);
            resetListRefreshTracking();
            recentEntries.length = 0;
        });
        vi.mocked(loadVisualizations).mockReset();
        resetListRefreshTracking();
        recentEntries.length = 0;
    });

    it("maps a visualization to the display route the grid opens", async () => {
        respondWithList(getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }));

        const sections = await searchScopedVisualizations(VISUALIZATION_SCOPE, "atac", makeCtx());
        const items = sections[0]?.items ?? [];

        expect(items).toHaveLength(1);
        expect(items[0]?.id).toBe("visualizations:viz-1");
        expect(items[0]?.title).toBe("ATAC peaks");
        expect(items[0]?.to).toBe("/visualizations/display?visualization=nvd3_bar&visualization_id=viz-1");
        // the update time is midnight UTC, so the pinned zone shows the day before
        expect(items[0]?.subtitle).toBe("nvd3_bar · Jan 1, 2026");
    });

    it("hydrates the store once and ranks the cache before merging backend hits", async () => {
        // two of many, so the cache cannot answer every query alone
        vi.mocked(loadVisualizations).mockResolvedValue({
            data: [
                getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }),
                getFakeVisualizationSummary({ id: "viz-2", title: "Coverage plot" }),
            ],
            totalMatches: 30,
        });
        // hydrate through the palette, the way opening the scope does
        await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx());
        vi.mocked(loadVisualizations).mockClear();
        // the backend repeats the cached match, which must not be listed twice
        vi.mocked(loadVisualizations).mockResolvedValueOnce({
            data: [getFakeVisualizationSummary({ id: "viz-2", title: "Coverage plot" })],
            totalMatches: 1,
        });

        const sections = await searchScopedVisualizations(VISUALIZATION_SCOPE, "coverage", makeCtx());

        // hydration already happened, so only the query fetch is left
        expect(loadVisualizations).toHaveBeenCalledTimes(1);
        expect(loadVisualizations).toHaveBeenCalledWith(expect.objectContaining({ search: "coverage", showOwn: true }));
        expect(sections[0]?.items.map((item) => item.id)).toEqual(["visualizations:viz-2"]);
    });

    it("queries the backend when the cache cannot answer and merges results into the store", async () => {
        vi.mocked(loadVisualizations).mockResolvedValueOnce({
            data: [getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" })],
            totalMatches: 30,
        });
        vi.mocked(loadVisualizations).mockResolvedValueOnce({
            data: [getFakeVisualizationSummary({ id: "viz-9", title: "Genome browser" })],
            totalMatches: 1,
        });

        const sections = await searchScopedVisualizations(VISUALIZATION_SCOPE, "genome", makeCtx());

        expect(loadVisualizations).toHaveBeenCalledTimes(2);
        expect(sections[0]?.items.map((item) => item.id)).toEqual(["visualizations:viz-9"]);
        expect(useVisualizationStore(pinia).getVisualizationSummary("viz-9")?.title).toBe("Genome browser");
    });

    it("answers from a cache holding every visualization without searching", async () => {
        respondWithList(getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }));
        await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx());
        vi.mocked(loadVisualizations).mockClear();

        const sections = renderedSections(await searchScopedVisualizations(VISUALIZATION_SCOPE, "genome", makeCtx()));

        expect(sections).toEqual([]);
        expect(loadVisualizations).not.toHaveBeenCalled();
    });

    it("refreshes the cached visualizations in the background once they go stale", async () => {
        respondWithList(getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }));
        await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx());
        vi.mocked(loadVisualizations).mockClear();

        // a later palette session, past the refresh interval
        resetListRefreshTracking();
        const sections = renderedSections(await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx()));

        expect(sections[0]?.items.map((item) => item.id)).toEqual(["visualizations:viz-1"]);
        expect(loadVisualizations).toHaveBeenCalledTimes(1);
    });

    it("filters the cache in the unscoped fan-out and never fetches there", async () => {
        respondWithList(
            getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }),
            getFakeVisualizationSummary({ id: "viz-2", title: "Coverage plot" }),
        );
        // nothing cached yet: the fan-out contributes nothing rather than fetching
        expect(await visualizationsProvider.search("coverage", makeCtx())).toEqual([]);
        expect(loadVisualizations).not.toHaveBeenCalled();

        await useVisualizationStore(pinia).ensureVariantLoaded("my");
        vi.mocked(loadVisualizations).mockClear();

        const items = await visualizationsProvider.search("coverage", makeCtx());

        expect(items.map((item) => item.id)).toEqual(["visualizations:viz-2"]);
        expect(loadVisualizations).not.toHaveBeenCalled();
    });

    it("shows recent and latest sections for an empty scoped query", async () => {
        respondWithList(
            getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }),
            getFakeVisualizationSummary({ id: "viz-2", title: "Coverage plot" }),
        );
        recentEntries.push({ type: "visualization", id: "viz-2", name: "Coverage plot" });

        const sections = await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx());

        expect(sections?.map((section) => section.title)).toEqual(["Recent", "Latest visualizations"]);
        expect(sections?.[0]?.items.map((item) => item.id)).toEqual(["visualizations:viz-2"]);
        expect(sections?.[1]?.items.map((item) => item.id)).toEqual(["visualizations:viz-1", "visualizations:viz-2"]);
    });

    it("keeps a recent item that is no longer cached, using its stored route", async () => {
        respondWithList();
        recentEntries.push({ type: "visualization", id: "viz-7", name: "Old chart", to: "/visualizations/edit?id=7" });

        const sections = renderedSections(await searchScopedVisualizations(VISUALIZATION_SCOPE, "", makeCtx()));

        expect(sections?.map((section) => section.title)).toEqual(["Recent"]);
        expect(sections?.[0]?.items[0]).toMatchObject({
            id: "visualizations:viz-7",
            title: "Old chart",
            to: "/visualizations/edit?id=7",
        });
    });

    it("returns a single result section for a scoped query", async () => {
        vi.mocked(loadVisualizations).mockResolvedValueOnce({
            data: [
                getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" }),
                getFakeVisualizationSummary({ id: "viz-2", title: "Coverage plot" }),
            ],
            totalMatches: 2,
        });
        vi.mocked(loadVisualizations).mockResolvedValueOnce({
            data: [getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" })],
            totalMatches: 1,
        });
        recentEntries.push({ type: "visualization", id: "viz-2", name: "Coverage plot" });

        const sections = await searchScopedVisualizations(VISUALIZATION_SCOPE, "atac", makeCtx());

        expect(sections).toHaveLength(1);
        expect(sections?.[0]?.id).toBe("results");
        expect(sections?.[0]?.items.map((item) => item.id)).toEqual(["visualizations:viz-1"]);
    });

    it("lists cached visualizations for an empty query without fetching", () => {
        const store = useVisualizationStore(pinia);
        store.saveVisualizations([getFakeVisualizationSummary({ id: "viz-1", title: "ATAC peaks" })]);
        store.visualizationIdsByVariant.my = ["viz-1"];

        const items = emptyQueryItems(makeCtx());

        expect(items.map((item) => item.id)).toEqual(["visualizations:viz-1"]);
        expect(loadVisualizations).not.toHaveBeenCalled();
    });
});
