import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, suppressLucideVue2Deprecation } from "@tests/vitest/helpers";
import { mount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { PiniaVuePlugin } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VueRouter from "vue-router";

import type { DCESummary, HDCASummary, HistorySummary } from "@/api";
import { useServerMock } from "@/api/client/__mocks__";
import { useCollectionElementsStore } from "@/stores/collectionElementsStore";

import CollectionPanel from "./CollectionPanel.vue";
import ContentItem from "@/components/History/Content/ContentItem.vue";

vi.mock("vue-router/composables", () => ({
    useRoute: vi.fn(() => ({ path: "/" })),
    useRouter: vi.fn(() => ({})),
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

async function mountPanel() {
    const wrapper = mount(CollectionPanel as object, {
        propsData: {
            history: HISTORY,
            selectedCollections: [COLLECTION],
            showControls: true,
        },
        localVue,
        router: new VueRouter(),
        pinia: createTestingPinia({ createSpy: vi.fn, stubActions: false }),
        stubs: {
            CollectionNavigation: true,
            CollectionDetails: true,
            DatasetDetails: true,
            CollectionCreatorIndex: true,
        },
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
        );
    });

    it("hands ContentItem the element's own dataset object", async () => {
        const wrapper = await mountPanel();

        const item = rows(wrapper).at(0).props("item");

        // Normalized at the fetch boundary, so the row gets a fully shaped dataset rather
        // than a copy derived per render.
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

        // The bug this guards: the panel bound `:item` to one object and passed a derived
        // copy to the selection handlers. Since ContentItem hands `props.item` back to the
        // click handler, a row must have exactly one identity -- and it has to be the one
        // the composable's positional range logic sees in `allItems`.
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

        // Selecting one would hand the creator a DCObject, which is neither a dataset nor
        // resolvable as an HDCA -- the "History dataset collection association not found"
        // path. The sub-collection branch never receives `select-click-handler`.
        expect(wrapper.text()).not.toContain("Build List");
    });

    it("writes a tag change back to the stored element", async () => {
        const wrapper = await mountPanel();

        const row = rows(wrapper).at(0);
        row.vm.$emit("tag-change", row.props("item"), ["added"]);
        await localVue.nextTick();

        // ContentItem holds no tag state of its own; the panel owns the item, so the row
        // only keeps showing the edit if the panel writes it back.
        expect(rows(wrapper).at(0).props("item").tags).toEqual(["added"]);
    });
});
