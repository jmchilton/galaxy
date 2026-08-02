import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, suppressLucideVue2Deprecation } from "@tests/vitest/helpers";
import { mount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { PiniaVuePlugin } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VueRouter from "vue-router";

import type { DCESummary, HDCASummary, HistorySummary } from "@/api";
import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useCollectionElementsStore } from "@/stores/collectionElementsStore";

import CollectionPanel from "./CollectionPanel.vue";
import ContentItem from "@/components/History/Content/ContentItem.vue";
import ListingLayout from "@/components/History/Layout/ListingLayout.vue";

vi.mock("vue-router/composables", () => ({
    useRoute: vi.fn(() => ({ path: "/" })),
    useRouter: vi.fn(() => ({})),
}));

// `stubs` does not reach children imported by a <script setup> parent, so stub the module.
// The panel's contract with the creator is the `selectedItems` it hands over.
vi.mock("@/components/Collections/CollectionCreatorIndex.vue", () => ({
    default: {
        name: "CollectionCreatorIndex",
        props: {
            historyId: String,
            collectionType: String,
            extendedCollectionType: Object,
            selectedItems: Array,
            show: Boolean,
            hideOnCreate: Boolean,
        },
        render: (h: (tag: string) => unknown) => h("div"),
    },
}));

const { server, http } = useServerMock();

const localVue = getLocalVue();
localVue.use(VueRouter);
localVue.use(PiniaVuePlugin);

const HISTORY: HistorySummary = {
    id: "history_id",
    name: "test history",
    model_class: "History",
    deleted: false,
    archived: false,
    purged: false,
    published: false,
    annotation: null,
    update_time: "2021-09-01T00:00:00.000Z",
    tags: [],
    url: "/history/history_id",
    contents_active: { active: 3, deleted: 0, hidden: 0 },
    count: 3,
    size: 0,
} as unknown as HistorySummary;

const COLLECTION: HDCASummary = {
    id: "hdca_id",
    collection_id: "dc_id",
    history_content_type: "dataset_collection",
    collection_type: "list",
    element_count: 3,
    populated_state: "ok",
    model_class: "HistoryDatasetCollectionAssociation",
    name: "a list",
    history_id: "history_id",
    tags: [],
    elements_datatypes: ["txt"],
    elements_states: { ok: 3 },
    elements_deleted: 0,
    deleted: false,
    visible: true,
    hid: 1,
    populated: true,
    contents_url: "/api/dataset_collections/hdca_id/contents/dc_id",
    create_time: "2021-09-01T00:00:00.000Z",
    update_time: "2021-09-01T00:00:00.000Z",
    url: "/api/histories/history_id/contents/dataset_collections/hdca_id",
    type_id: "dataset_collection-hdca_id",
    type: "collection",
} as unknown as HDCASummary;

/** Two datasets and one sub-collection, mirroring what the contents API returns. */
function elementsPayload(): DCESummary[] {
    const dataset = (index: number): DCESummary =>
        ({
            id: `dce_${index}`,
            element_index: index,
            element_identifier: `element ${index}`,
            element_type: "hda",
            model_class: "DatasetCollectionElement",
            object: {
                id: `hda_${index}`,
                model_class: "HistoryDatasetAssociation",
                state: "ok",
                hda_ldda: "hda",
                history_id: "history_id",
                tags: [],
                accessible: true,
                purged: false,
                // Deliberately no `name` and no `history_content_type`: the contents API
                // serializes elements via `dictify_element_reference`, which omits both.
            },
        }) as unknown as DCESummary;

    return [
        dataset(0),
        dataset(1),
        {
            id: "dce_2",
            element_index: 2,
            element_identifier: "nested",
            element_type: "dataset_collection",
            model_class: "DatasetCollectionElement",
            object: {
                id: "sub_dc_id",
                model_class: "DatasetCollection",
                collection_type: "list",
                element_count: 0,
                populated: true,
                elements: [],
                elements_states: {},
                elements_deleted: 0,
                elements_datatypes: [],
            },
        } as unknown as DCESummary,
    ];
}

async function mountPanel(collection: HDCASummary = COLLECTION) {
    const wrapper = mount(CollectionPanel as object, {
        propsData: {
            history: HISTORY,
            selectedCollections: [collection],
            showControls: true,
        },
        localVue,
        router: new VueRouter(),
        pinia: createTestingPinia({ createSpy: vi.fn, stubActions: false }),
    });
    await flushPromises();
    return wrapper;
}

/** The rows the panel rendered, in listing order. */
function rows(wrapper: Wrapper<Vue>) {
    return wrapper.findAllComponents(ContentItem);
}

function ctrlClick(row: Wrapper<Vue>) {
    // ContentItem binds the click on its inner title area, not its root element.
    // eventStore.isCtrlKey reads metaKey on Mac and ctrlKey elsewhere; set both so the
    // test does not depend on the simulated platform.
    return row.find(".p-1.cursor-pointer").trigger("click", { ctrlKey: true, metaKey: true });
}

function shiftClick(row: Wrapper<Vue>) {
    return row.find(".p-1.cursor-pointer").trigger("click", { shiftKey: true });
}

function selectionCount(wrapper: Wrapper<Vue>) {
    const label = wrapper.text().match(/Build List \((\d+)\)/);
    return label ? Number(label[1]) : 0;
}

describe("CollectionPanel", () => {
    beforeEach(() => {
        suppressLucideVue2Deprecation();
        server.use(
            http.get("/api/dataset_collections/{hdca_id}/contents/{parent_id}", ({ response }) => {
                return response(200).json(elementsPayload());
            }),
            http.get("/api/object_stores", ({ response }) => {
                return response(200).json([]);
            }),
            http.get("/api/configuration", ({ response }) => {
                return response(200).json({});
            }),
            // The fields the contents endpoint does not serialize for collection elements.
            http.get("/api/datasets/{dataset_id}", ({ response, params }) => {
                return response.untyped(
                    HttpResponse.json({
                        id: params.dataset_id,
                        model_class: "HistoryDatasetAssociation",
                        history_content_type: "dataset",
                        name: `element ${String(params.dataset_id).split("_")[1]}`,
                        extension: "txt",
                        hid: 7,
                        deleted: false,
                        visible: false,
                        purged: false,
                        state: "ok",
                        history_id: "history_id",
                        tags: [],
                    }),
                );
            }),
        );
    });

    it("hands ContentItem the element's own dataset object", async () => {
        const wrapper = await mountPanel();

        const item = rows(wrapper).at(0).props("item");

        expect(item).toMatchObject({
            id: "hda_0",
            name: "element 0",
            history_content_type: "dataset",
        });
    });

    it("renders the store's own element object, not a derived copy", async () => {
        const wrapper = await mountPanel();

        const store = useCollectionElementsStore();
        const stored = store.getCollectionElements(COLLECTION) as DCESummary[];

        // ContentItem hands `props.item` back to the click handler, so a row must have
        // exactly one identity, and it has to be the one the composable's positional range
        // logic sees in `allItems`.
        expect(rows(wrapper).at(0).props("item")).toBe(stored[0]!.object);
        expect(rows(wrapper).at(1).props("item")).toBe(stored[1]!.object);
    });

    it("counts a ctrl-clicked dataset row as selected", async () => {
        const wrapper = await mountPanel();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        await ctrlClick(rows(wrapper).at(0));

        expect(rows(wrapper).at(0).props("selected")).toBe(true);
        expect(wrapper.text()).toContain("Build List (1)");
    });

    it("does not select sub-collection rows", async () => {
        const wrapper = await mountPanel();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        await ctrlClick(rows(wrapper).at(2));

        // Selecting one would hand the creator a DCObject, which it cannot resolve.
        expect(wrapper.text()).not.toContain("Build List");
    });

    it("hands the creator datasets the builders can actually use", async () => {
        const wrapper = await mountPanel();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");
        await ctrlClick(rows(wrapper).at(0));

        await wrapper
            .findAll("button")
            .filter((b) => b.text().includes("Build List"))
            .at(0)
            .trigger("click");
        await flushPromises();

        const creator = wrapper.findComponent({ name: "CollectionCreatorIndex" });
        const [seeded] = creator.props("selectedItems");

        // The creator resolves what it is handed as a dataset, and its mixed-extension
        // warning and messages read `extension`/`hid`, which the contents API omits.
        expect(seeded).toMatchObject({
            id: "hda_0",
            history_content_type: "dataset",
            name: "element 0",
            extension: "txt",
            hid: 7,
        });
    });

    it("says nothing about loading when every element is present", async () => {
        const wrapper = await mountPanel();

        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        expect(wrapper.text()).not.toContain("not loaded");
    });

    it("writes a tag change back to the stored element", async () => {
        const wrapper = await mountPanel();

        const row = rows(wrapper).at(0);
        row.vm.$emit("tag-change", row.props("item"), ["added"]);
        await localVue.nextTick();

        // ContentItem holds no tag state of its own, so the row only keeps showing the
        // edit if the panel writes it back.
        expect(rows(wrapper).at(0).props("item").tags).toEqual(["added"]);
    });
});

/** A collection larger than one fetch window. `collectionElementsStore` seeds one
 * placeholder per element and fills a 50-wide window at a time, so scrolling to a far
 * offset leaves a gap of unloaded rows in the middle of the rendering. */
describe("CollectionPanel with unloaded elements", () => {
    const TOTAL = 120;
    const BIG_COLLECTION = { ...COLLECTION, element_count: TOTAL, name: "big list" } as HDCASummary;

    function pagedElement(index: number): DCESummary {
        return {
            id: `dce_${index}`,
            element_index: index,
            element_identifier: `element ${index}`,
            element_type: "hda",
            model_class: "DatasetCollectionElement",
            object: {
                id: `hda_${index}`,
                model_class: "HistoryDatasetAssociation",
                state: "ok",
                hda_ldda: "hda",
                history_id: "history_id",
                tags: [],
                accessible: true,
                purged: false,
            },
        } as unknown as DCESummary;
    }

    /** Loads the first window, then a window at the far end, leaving rows 50-69 unloaded. */
    async function mountWithGap() {
        const wrapper = await mountPanel(BIG_COLLECTION);
        wrapper.findComponent(ListingLayout).vm.$emit("scroll", 70);
        await flushPromises();
        await flushPromises();
        return wrapper;
    }

    beforeEach(() => {
        suppressLucideVue2Deprecation();
        server.use(
            http.get("/api/dataset_collections/{hdca_id}/contents/{parent_id}", ({ response, query }) => {
                const offset = Number(query.get("offset") ?? 0);
                const limit = Number(query.get("limit") ?? 50);
                const page: DCESummary[] = [];
                for (let i = offset; i < Math.min(offset + limit, TOTAL); i++) {
                    page.push(pagedElement(i));
                }
                return response(200).json(page);
            }),
            http.get("/api/object_stores", ({ response }) => response(200).json([])),
            http.get("/api/configuration", ({ response }) => response(200).json({})),
        );
    });

    it("renders every element but leaves the unfetched ones as placeholders", async () => {
        const wrapper = await mountWithGap();

        const all = rows(wrapper).wrappers;
        expect(all).toHaveLength(TOTAL);
        expect(all.filter((row) => row.props("isPlaceholder") === true)).toHaveLength(20);
    });

    it("selects only the loaded rows when a range spans unloaded ones", async () => {
        const wrapper = await mountWithGap();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        const all = rows(wrapper);
        await ctrlClick(all.at(49));
        await shiftClick(all.at(70));

        // 22 rows were dragged over, but rows 50-69 have no dataset behind them yet, so
        // only the two loaded ends can be selected. `allItems` holds loaded datasets only
        // and compaction preserves order, so the range is the right *set* -- it is just
        // silently smaller than the span the user swept.
        expect(selectionCount(wrapper)).toBe(2);
    });

    it("reports the loaded count on select-all rather than the collection's size", async () => {
        const wrapper = await mountWithGap();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        await rows(wrapper).at(0).trigger("keydown", { key: "a", ctrlKey: true, metaKey: true });
        await flushPromises();

        // The panel passes no `querySelection`, so select-all cannot claim the 120 the
        // collection holds. "Build List" would otherwise promise datasets it never fetched.
        expect(selectionCount(wrapper)).toBe(100);
    });

    it("says how many elements the selection cannot reach", async () => {
        const wrapper = await mountWithGap();

        // Nothing to warn about until the user is actually selecting.
        expect(wrapper.text()).not.toContain("not loaded");

        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        // Selecting everything here builds a list of 100 out of 120. That the missing 20
        // cannot be selected is inherent; saying so is what keeps the build honest.
        expect(wrapper.text()).toContain("20 not loaded");
    });

    it("stops warning once the missing elements arrive", async () => {
        const wrapper = await mountWithGap();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");
        expect(wrapper.text()).toContain("20 not loaded");

        wrapper.findComponent(ListingLayout).vm.$emit("scroll", 50);
        await flushPromises();
        await flushPromises();

        expect(wrapper.text()).not.toContain("not loaded");
    });
});

/** A `list` may hold the same HDA under two element identifiers. Selection keys on the
 * dataset, so those two rows share one key and the selection holds fewer entries than the
 * listing has rows. */
describe("CollectionPanel with a duplicated dataset element", () => {
    function duplicateElements(): DCESummary[] {
        const element = (index: number, hdaId: string): DCESummary =>
            ({
                id: `dce_${index}`,
                element_index: index,
                element_identifier: `element ${index}`,
                element_type: "hda",
                model_class: "DatasetCollectionElement",
                object: {
                    id: hdaId,
                    model_class: "HistoryDatasetAssociation",
                    state: "ok",
                    hda_ldda: "hda",
                    history_id: "history_id",
                    tags: [],
                    accessible: true,
                    purged: false,
                },
            }) as unknown as DCESummary;

        // Rows 0 and 2 are the same underlying dataset.
        return [element(0, "hda_dup"), element(1, "hda_other"), element(2, "hda_dup")];
    }

    beforeEach(() => {
        suppressLucideVue2Deprecation();
        server.use(
            http.get("/api/dataset_collections/{hdca_id}/contents/{parent_id}", ({ response }) =>
                response(200).json(duplicateElements()),
            ),
            http.get("/api/object_stores", ({ response }) => response(200).json([])),
            http.get("/api/configuration", ({ response }) => response(200).json({})),
        );
    });

    it("counts the datasets it actually holds when everything is selected", async () => {
        const wrapper = await mountPanel();
        await wrapper.find(".show-collection-content-selectors-btn").trigger("click");

        await rows(wrapper).at(0).trigger("keydown", { key: "a", ctrlKey: true, metaKey: true });
        await flushPromises();

        // Three rows collapse to two selected datasets. Reporting three would mean the
        // selection size disagreed with the map, which is exactly the condition the
        // composable reads as "query selection" -- a mode this panel has no query for, and
        // in which `isSelected` starts answering from a filter instead of the selection.
        expect(selectionCount(wrapper)).toBe(2);
    });
});
