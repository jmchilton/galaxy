import "@tests/vitest/mockHelpPopovers";
import "@/composables/__mocks__/filter";
import "../FormSelectMany/worker/__mocks__/selectMany";

import { createTestingPinia } from "@pinia/testing";
import { dispatchEvent, emittedArg, getLocalVue, nth } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";
import { testDatatypesMapper, typesAndMappingResponse } from "@/components/Datatypes/test_fixtures";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import { useEventStore } from "@/stores/eventStore";

import MountTarget from "./FormData.vue";

vi.mock("@/composables/filter");

const { server, http } = useServerMock();

// FormData resolves its datatypes mapper on mount; stub the request so the tests
// never hit a real fetch that gets aborted at teardown and surfaces as an
// unhandled error that fails the run.
server.use(
    http.get("/api/datatypes/types_and_mapping", ({ response }) => {
        return response(200).json(typesAndMappingResponse);
    }),
);

const localVue = getLocalVue();

let eventStore: ReturnType<typeof useEventStore>;

function createTarget(propsData: Record<string, any>) {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
    eventStore = useEventStore();
    const datatypesStore = useDatatypesMapperStore();
    datatypesStore.datatypesMapper = testDatatypesMapper;
    return mount(MountTarget as any, {
        global: localVue,
        props: propsData,
        pinia,
        stubs: {
            FontAwesomeIcon: true,
        },
    });
}

const defaultOptions = {
    dce: [
        { id: "dce1", name: "dceName1", src: "dce", is_dataset: true },
        { id: "dce2", name: "dceName2", src: "dce" },
        { id: "dce3", name: "dceName3", src: "dce", map_over_type: "mapOverType" },
        { id: "dce4", name: "dceName4", src: "dce", is_dataset: true },
    ],
    hda: [
        { id: "hda1", hid: 1, name: "hdaName1", src: "hda", tags: ["tag1"] },
        { id: "hda2", hid: 2, name: "hdaName2", src: "hda", tags: ["tag1", "tag2"] },
        { id: "hda3", hid: 3, name: "hdaName3", src: "hda", tags: ["tag2", "tag3"] },
        { id: "hda4", hid: 4, name: "hdaName4", src: "hda" },
    ],
    hdca: [
        { id: "hdca5", hid: 5, name: "hdcaName5", src: "hdca" },
        { id: "hdca6", hid: 6, name: "hdcaName6", src: "hdca" },
    ],
};

// inputs accepting both X and list:X list a list:list collection twice: directly and mapped over
const nestedListProps = {
    type: "data_collection",
    collectionTypes: ["list", "list:list"],
    options: {
        hdca: [
            { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", collection_type: "list:list" },
            { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", collection_type: "list:list", map_over_type: "list" },
            { id: "hdcaL", hid: 8, name: "flat", src: "hdca", collection_type: "list" },
        ],
    },
};

const SELECT_OPTIONS = ".multiselect__element";
const SELECTED_VALUE = ".multiselect__option--selected";

// vue-multiselect only renders its option list (and thus SELECT_OPTIONS /
// SELECTED_VALUE) while its dropdown is open, so tests need to open it
// before reading those. Selecting a new value in single-select mode closes
// the dropdown again, so callers re-open as needed between assertions.
async function openMultiselect(wrapper: ReturnType<typeof createTarget>) {
    if (!wrapper.find(".multiselect__content-wrapper").exists()) {
        await wrapper.find(".multiselect__select").trigger("mousedown");
    }
}

describe("FormData", () => {
    it("regular data", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
        });
        const value_0 = {
            batch: false,
            product: false,
            values: [{ id: "dce4", src: "dce", map_over_type: null }],
        };
        const value_1 = {
            batch: false,
            product: false,
            values: [{ id: "hda1", src: "hda", map_over_type: null }],
        };
        const value_2 = {
            batch: false,
            product: false,
            values: [{ id: "hda4", src: "hda", map_over_type: null }],
        };
        const options = wrapper.find(".g-button-group").findAll("button");
        expect(options.length).toBe(4);
        expect(nth(options, 0).classes()).toContain("g-pressed");
        expect(nth(options, 0).attributes("title")).toBe("Single dataset");
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await openMultiselect(wrapper);
        expect(wrapper.find(SELECTED_VALUE).text()).toContain("dceName4 (as dataset)");
        await wrapper.setProps({ value: value_0 });
        expect(wrapper.emitted("input")).toHaveLength(1);
        await wrapper.setProps({ value: { values: [{ id: "hda2", src: "hda" }] } });
        await openMultiselect(wrapper);
        expect(wrapper.find(SELECTED_VALUE).text()).toContain("2: hdaName2");
        expect(wrapper.emitted("input")).toHaveLength(1);
        await openMultiselect(wrapper);
        const elements_0 = wrapper.findAll(SELECT_OPTIONS);
        expect(elements_0.length).toEqual(6);
        await nth(elements_0, 2).find("span").trigger("click");
        expect(wrapper.emitted("input")).toHaveLength(2);
        expect(emittedArg(wrapper, "input", 1)).toEqual(value_1);
        await wrapper.setProps({ value: value_2 });
        await openMultiselect(wrapper);
        expect(wrapper.find(SELECTED_VALUE).text()).toContain("4: hdaName4");
    });

    it("optional dataset", async () => {
        const wrapper = createTarget({
            value: null,
            optional: true,
            options: defaultOptions,
        });
        expect(emittedArg(wrapper, "input")).toEqual(null);
        expect(wrapper.emitted("input")).toHaveLength(1);
        await openMultiselect(wrapper);
        expect(wrapper.find(SELECTED_VALUE).text()).toEqual("Nothing selected");
        expect(wrapper.findAll(SELECT_OPTIONS).length).toBe(7);
    });

    it("styles the no-options alert to match the control height in both run and tool forms", async () => {
        const wrapper = createTarget({
            type: "data",
            value: null,
            options: {},
            workflowRun: true,
        });
        const alert = wrapper.find(".form-data-no-options-alert");
        expect(alert.exists()).toBe(true);
        expect(alert.text()).toBe("No datasets available");

        // The alert keeps the aligned styling outside of workflow runs too.
        await wrapper.setProps({ workflowRun: false });
        expect(wrapper.find(".form-data-no-options-alert").exists()).toBe(true);
    });

    it("multiple datasets", async () => {
        const wrapper = createTarget({
            value: {
                values: [
                    { id: "hda2", src: "hda" },
                    { id: "hda3", src: "hda" },
                ],
            },
            multiple: true,
            optional: true,
            options: defaultOptions,
        });
        const options = wrapper.find(".g-button-group").findAll("button");
        expect(options.length).toBe(3);
        expect(nth(options, 0).classes()).toContain("g-pressed");
        expect(nth(options, 0).attributes("title")).toBe("Multiple datasets");
        expect(emittedArg(wrapper, "input")).toEqual({
            batch: false,
            product: false,
            values: [
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "hda3", map_over_type: null, src: "hda" },
            ],
        });
        expect(wrapper.emitted("input")).toHaveLength(1);
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(2);
        expect(nth(selectedValues, 0).text()).toContain("2: hdaName2");
        expect(nth(selectedValues, 1).text()).toContain("3: hdaName3");
        const value_0 = {
            batch: false,
            product: false,
            values: [
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "hda3", map_over_type: null, src: "hda" },
            ],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await nth(selectedValues, 0).trigger("click");
        const value_1 = {
            batch: false,
            product: false,
            values: [{ id: "hda3", map_over_type: null, src: "hda" }],
        };
        expect(emittedArg(wrapper, "input", 1)).toEqual(value_1);
        await wrapper.setProps({ value: value_1 });
        await nth(selectedValues, 1).trigger("click");
        const value_2 = {
            batch: false,
            product: false,
            values: [{ id: "hda3", map_over_type: null, src: "hda" }],
        };
        expect(emittedArg(wrapper, "input", 1)).toEqual(value_2);
        await wrapper.setProps({ value: value_2 });
        expect(wrapper.emitted("input")).toHaveLength(3);
        expect(emittedArg(wrapper, "input", 2)).toEqual(null);
    });

    it("properly sorts multiple datasets", async () => {
        const wrapper = createTarget({
            value: {
                // the order of values does matter here
                values: [
                    { id: "hda2", src: "hda" },
                    { id: "hda3", src: "hda" },
                    { id: "hda1", src: "hda" },
                ],
            },
            multiple: true,
            optional: true,
            options: defaultOptions,
        });
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(3);
        // the values in the multiselect are sorted by hid ASC
        expect(nth(selectedValues, 0).text()).toContain("1: hdaName1");
        expect(nth(selectedValues, 1).text()).toContain("2: hdaName2");
        expect(nth(selectedValues, 2).text()).toContain("3: hdaName3");
        await nth(selectedValues, 0).trigger("click");
        const value_sorted = {
            batch: false,
            product: false,
            values: [
                // the values in the emitted input are sorted by hid ASC
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "hda3", map_over_type: null, src: "hda" },
            ],
        };
        expect(emittedArg(wrapper, "input", 1)).toEqual(value_sorted);
    });

    it("sorts mixed dces and hdas", async () => {
        const sortOptions = {
            hda: [
                { id: "hda1", hid: 1, name: "hdaName1", src: "hda", tags: ["tag1"] },
                { id: "hda2", hid: 2, name: "hdaName2", src: "hda", tags: ["tag1", "tag2"] },
                { id: "hda3", hid: 3, name: "hdaName3", src: "hda", tags: ["tag2", "tag3"] },
                { id: "hda4", hid: 4, name: "hdaName4", src: "hda" },
            ],
            dce: [
                { id: "dce1", name: "dceName1", src: "dce", is_dataset: true },
                { id: "dce2", name: "dceName2", src: "dce", is_dataset: true },
                { id: "dce3", name: "dceName3", src: "dce", is_dataset: true },
                { id: "dce4", name: "dceName4", src: "dce", is_dataset: true },
            ],
        };
        const wrapper = createTarget({
            //intermix hdas and dces in the selected options
            value: {
                values: [
                    { id: "hda1", src: "hda" },
                    { id: "dce4", src: "dce" },
                    { id: "dce2", src: "dce" },
                    { id: "hda2", src: "hda" },
                    { id: "dce3", src: "dce" },
                ],
            },
            multiple: true,
            optional: true,
            options: sortOptions,
        });
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(5);
        expect(nth(selectedValues, 0).text()).toContain("dceName4 (as dataset)");
        expect(nth(selectedValues, 1).text()).toContain("dceName3 (as dataset)");
        expect(nth(selectedValues, 2).text()).toContain("dceName2 (as dataset)");
        expect(nth(selectedValues, 3).text()).toContain("1: hdaName1");
        expect(nth(selectedValues, 4).text()).toContain("2: hdaName2");
        await nth(selectedValues, 0).trigger("click");
        const value_sorted = {
            batch: false,
            product: false,
            values: [
                { id: "hda1", map_over_type: null, src: "hda" },
                { id: "dce2", map_over_type: null, src: "dce" },
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "dce3", map_over_type: null, src: "dce" },
            ],
        };
        expect(emittedArg(wrapper, "input", 1)).toEqual(value_sorted);
    });

    it("dataset collection as hda", async () => {
        const wrapper = createTarget({
            value: { values: [{ id: "dce1", src: "dce" }] },
            options: defaultOptions,
        });
        const value_0 = {
            batch: false,
            product: false,
            values: [{ id: "dce1", map_over_type: null, src: "dce" }],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        expect(wrapper.emitted("input")).toHaveLength(1);
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("dceName1 (as dataset)");
    });

    it("dataset collection element as hdca without map_over_type", async () => {
        const wrapper = createTarget({
            value: { values: [{ id: "dce2", src: "dce" }] },
            options: defaultOptions,
        });
        const value_0 = { batch: true, product: false, values: [{ id: "dce2", map_over_type: null, src: "dce" }] };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await wrapper.vm.$nextTick();
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("dceName2 (as dataset collection)");
    });

    it("dataset collection element as hdca mapped to batch field", async () => {
        const wrapper = createTarget({
            value: { values: [{ id: "dce3", src: "dce" }] },
            options: defaultOptions,
        });
        const value_0 = {
            batch: true,
            product: false,
            values: [{ id: "dce3", map_over_type: "mapOverType", src: "dce" }],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await wrapper.vm.$nextTick();
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("dceName3 (as dataset collection)");
    });

    it("dataset collection element as hdca mapped to non-batch field", async () => {
        const wrapper = createTarget({
            type: "data_collection",
            value: { values: [{ id: "dce3", src: "dce" }] },
            options: defaultOptions,
        });
        const value_0 = {
            batch: true,
            product: false,
            values: [{ id: "dce3", map_over_type: "mapOverType", src: "dce" }],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await wrapper.vm.$nextTick();
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("dceName3 (as dataset collection)");
    });

    it("dataset collection mapped to non-batch field", async () => {
        const wrapper = createTarget({
            type: "data_collection",
            value: { values: [{ id: "hdca5", src: "hdca" }] },
            options: defaultOptions,
        });
        const value_0 = {
            batch: false,
            product: false,
            values: [{ id: "hdca5", map_over_type: null, src: "hdca" }],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
        await wrapper.vm.$nextTick();
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("5: hdcaName5");
    });

    it("multiple dataset collection elements (as hdas)", async () => {
        const wrapper = createTarget({
            value: {
                values: [
                    { id: "dce1", src: "dce" },
                    { id: "dce4", src: "dce" },
                ],
            },
            options: defaultOptions,
        });
        const value_0 = {
            batch: true,
            product: false,
            values: [
                { id: "dce1", map_over_type: null, src: "dce" },
                { id: "dce4", map_over_type: null, src: "dce" },
            ],
        };
        expect(emittedArg(wrapper, "input")).toEqual(value_0);
    });

    it("dropping values", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
        });
        eventStore.setDragData({ id: "hdca4", history_content_type: "dataset_collection" });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "input", 1)).toEqual({
            batch: true,
            product: false,
            values: [{ id: "hdca4", map_over_type: null, src: "hdca" }],
        });
        eventStore.setDragData({ id: "hda2", history_content_type: "dataset" });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "input", 2)).toEqual({
            batch: false,
            product: false,
            values: [{ id: "hda2", map_over_type: null, src: "hda" }],
        });
    });

    it("rejects hda on collection input", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
            type: "data_collection",
        });
        eventStore.setDragData({ id: "whatever", history_content_type: "dataset" });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "alert")).toEqual("dataset is not a valid input for dataset collection parameter.");
    });

    it("rejects paired collection on list collection input", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
            type: "data_collection",
            collectionTypes: ["list"],
        });
        eventStore.setDragData({
            id: "whatever",
            history_content_type: "dataset_collection",
            collection_type: "paired",
        });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "alert")).toEqual(
            "dataset pair dataset collection is not a valid input for list type dataset collection parameter.",
        );
    });

    it("accepts list:list collection on list collection input", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
            type: "data_collection",
            collectionTypes: ["list"],
        });
        eventStore.setDragData({
            id: "whatever",
            history_content_type: "dataset_collection",
            collection_type: "list:list",
        });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(wrapper.emitted("alert")).toBeUndefined();
    });

    it("rejects list:paired_or_unpaired collection on paired collection input", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
            type: "data_collection",
            collectionTypes: ["paired"],
        });
        eventStore.setDragData({
            id: "whatever",
            history_content_type: "dataset_collection",
            collection_type: "list:paired_or_unpaired",
        });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "alert")).toEqual(
            "mixed list of paired and unpaired dataset collection is not a valid input for paired type dataset collection parameter.",
        );
    });

    it("rejects paired collection on list:paired_or_unpaired collection input", async () => {
        const wrapper = createTarget({
            value: null,
            options: defaultOptions,
            type: "data_collection",
            collectionTypes: ["list:paired_or_unpaired"],
        });
        eventStore.setDragData({
            id: "whatever",
            history_content_type: "dataset_collection",
            collection_type: "paired",
        });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "alert")).toContain("dataset pair dataset collection is not a valid input");
    });

    it.each([
        ["list", "single_datasets"],
        ["list:paired", "paired"],
    ])("maps a dropped %s over a paired_or_unpaired input like the server", async (collectionType, mapOverType) => {
        const wrapper = createTarget({
            value: null,
            options: { hdca: [] },
            type: "data_collection",
            collectionTypes: ["paired_or_unpaired"],
        });
        await wrapper.vm.$nextTick();
        const before = wrapper.emitted("input")?.length ?? 0;
        eventStore.setDragData({
            id: "hdcaX",
            hid: 3,
            name: "dropped",
            history_content_type: "dataset_collection",
            collection_type: collectionType,
        });
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(wrapper.emitted("alert")).toBeUndefined();
        expect(emittedArg(wrapper, "input", before)).toEqual({
            batch: true,
            product: false,
            values: [{ id: "hdcaX", map_over_type: mapOverType, src: "hdca" }],
        });
    });

    it("linked and unlinked batch mode handling", async () => {
        const wrapper = createTarget({
            value: null,
            flavor: "module",
            options: defaultOptions,
        });
        expect(emittedArg(wrapper, "input")).toEqual({
            batch: false,
            product: false,
            values: [{ id: "dce4", map_over_type: null, src: "dce" }],
        });
        const noCheckLinked = wrapper.find("input[type='checkbox']");
        expect(noCheckLinked.exists()).toBeFalsy();
        await wrapper.find("[title='Multiple datasets']").trigger("click");
        expect(emittedArg(wrapper, "input", 1)).toEqual(null);
        await openMultiselect(wrapper);
        const elements_0 = wrapper.findAll(SELECT_OPTIONS);
        expect(elements_0.length).toEqual(6);
        await nth(elements_0, 3).find("span").trigger("click");
        const value_0 = {
            batch: true,
            product: false,
            values: [{ id: "hda2", map_over_type: null, src: "hda" }],
        };
        expect(emittedArg(wrapper, "input", 2)).toEqual(value_0);
        await wrapper.setProps({ value: value_0 });
        await nth(elements_0, 0).find("span").trigger("click");
        const value_1 = {
            batch: true,
            product: false,
            values: [
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "dce4", map_over_type: null, src: "dce" },
            ],
        };
        expect(emittedArg(wrapper, "input", 3)).toEqual(value_1);
        await wrapper.setProps({ value: value_1 });
        const checkLinked = wrapper.find("input[type='checkbox']");
        expect(wrapper.find(".custom-switch span").text()).toBe(
            "Linked:Datasets will be run in matched order with other datasets.",
        );
        expect((checkLinked.element as HTMLInputElement).checked).toBeTruthy();
        await checkLinked.setValue(false);
        expect(wrapper.find(".custom-switch span").text()).toBe(
            "Unlinked:Dataset will be run against *all* other datasets.",
        );
        expect(emittedArg(wrapper, "input", 4)).toEqual({
            batch: true,
            product: true,
            values: [
                { id: "hda2", map_over_type: null, src: "hda" },
                { id: "dce4", map_over_type: null, src: "dce" },
            ],
        });
    });

    it("match dataset collection on initial value", async () => {
        const wrapper = createTarget({
            value: {
                values: [{ id: "hdca5", src: "hdca" }],
            },
            multiple: true,
            options: defaultOptions,
        });
        await wrapper.vm.$nextTick();
        const options = wrapper.find(".g-button-group").findAll("button");
        expect(options.length).toBe(3);
        expect(nth(options, 1).classes()).toContain("g-pressed");
        expect(nth(options, 1).attributes("title")).toBe("Dataset collection");
        for (const i of [0, 1]) {
            expect(emittedArg(wrapper, "input", i)).toEqual({
                batch: false,
                product: false,
                values: [{ id: "hdca5", map_over_type: null, src: "hdca" }],
            });
        }
        expect(wrapper.emitted("input")).toHaveLength(2);
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toBe("5: hdcaName5");
        await wrapper.find("[title='Multiple datasets']").trigger("click");
        expect(nth(options, 0).classes()).toContain("g-pressed");
        expect(emittedArg(wrapper, "input", 2)).toEqual(null);
    });

    it("renders pinned entries alongside paged options", async () => {
        // Pinned entries are forced-include items the server returned because
        // they're selected but landed outside the current page window. The
        // dropdown must show them so the user can see what's pre-selected.
        const wrapper = createTarget({
            value: { values: [{ id: "hdaPinned", src: "hda" }] },
            options: { hda: defaultOptions.hda },
            pinned: {
                hda: [{ id: "hdaPinned", hid: 999, name: "OldDataset", src: "hda", keep: true, tags: [] }],
            },
        });
        await wrapper.vm.$nextTick();
        await openMultiselect(wrapper);
        const selectedValues = wrapper.findAll(SELECTED_VALUE);
        expect(selectedValues.length).toBe(1);
        expect(nth(selectedValues, 0).text()).toContain("999: OldDataset");
    });

    describe("map-over options", () => {
        const MAP_OVER_MARKER = ".form-data-map-over-marker";

        function allEmitted(wrapper: ReturnType<typeof createTarget>) {
            return (wrapper.emitted("input") ?? []).map((args) => args[0]);
        }

        it("keeps a selected mapped-over entry of a collection also listed directly", async () => {
            const wrapper = createTarget({
                ...nestedListProps,
                value: { values: [{ id: "hdcaLL", src: "hdca", map_over_type: "list" }] },
            });
            await wrapper.vm.$nextTick();
            const emitted = allEmitted(wrapper);
            expect(emitted.length).toBeGreaterThan(0);
            for (const value of emitted) {
                expect(value).toEqual({
                    batch: true,
                    product: false,
                    values: [{ id: "hdcaLL", map_over_type: "list", src: "hdca" }],
                });
            }
            await openMultiselect(wrapper);
            const selected = wrapper.findAll(SELECTED_VALUE);
            expect(selected.length).toBe(1);
            expect(nth(selected, 0).find(MAP_OVER_MARKER).text()).toBe("one job per list");
        });

        it("selects the direct entry for a value without a map-over type", async () => {
            const wrapper = createTarget({
                ...nestedListProps,
                value: { values: [{ id: "hdcaLL", src: "hdca" }] },
            });
            await wrapper.vm.$nextTick();
            for (const value of allEmitted(wrapper)) {
                expect(value).toEqual({
                    batch: false,
                    product: false,
                    values: [{ id: "hdcaLL", map_over_type: null, src: "hdca" }],
                });
            }
            await openMultiselect(wrapper);
            const selected = wrapper.findAll(SELECTED_VALUE);
            expect(selected.length).toBe(1);
            expect(nth(selected, 0).find(MAP_OVER_MARKER).exists()).toBe(false);
        });

        it("marks only the entries that map over", async () => {
            const wrapper = createTarget({ ...nestedListProps, value: null });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            const options = wrapper.findAll(SELECT_OPTIONS);
            expect(options.length).toBe(3);
            expect(nth(options, 0).find(MAP_OVER_MARKER).exists()).toBe(false);
            expect(nth(options, 1).find(MAP_OVER_MARKER).text()).toBe("one job per list");
            expect(nth(options, 2).find(MAP_OVER_MARKER).exists()).toBe(false);
            // the marker sits beside the label rather than inside it
            expect(nth(options, 1).find("[data-option-value] span").text()).toBe("9: nested");
        });

        it("switches to map over when the marked entry is chosen", async () => {
            const wrapper = createTarget({
                ...nestedListProps,
                value: { values: [{ id: "hdcaLL", src: "hdca" }] },
            });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            await nth(wrapper.findAll(SELECT_OPTIONS), 1).find(".multiselect__option").trigger("click");
            expect(emittedArg(wrapper, "input", -1)).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLL", map_over_type: "list", src: "hdca" }],
            });
        });

        it("names what each job receives", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                value: null,
                options: {
                    hdca: [
                        { id: "hdcaLP", hid: 7, name: "reads", src: "hdca", map_over_type: "paired" },
                        { id: "hdcaL", hid: 6, name: "singles", src: "hdca", map_over_type: "single_datasets" },
                        { id: "hdcaLLL", hid: 5, name: "deep", src: "hdca", map_over_type: "list:list" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            const markers = wrapper.findAll(MAP_OVER_MARKER).map((marker) => marker.text());
            expect(markers).toEqual([
                "one job per dataset pair",
                "one job per dataset",
                "one job per nested list:list",
            ]);
        });

        it("marks map-over entries in multiple select fields", async () => {
            const wrapper = createTarget({
                multiple: true,
                value: { values: [{ id: "hdcaLL", src: "hdca" }] },
                options: {
                    hdca: [
                        { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", map_over_type: "list" },
                        { id: "hdcaL", hid: 8, name: "flat", src: "hdca" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            const options = wrapper.findAll(SELECT_OPTIONS);
            expect(nth(options, 0).find(MAP_OVER_MARKER).text()).toBe("one job per list");
            expect(nth(options, 1).find(MAP_OVER_MARKER).exists()).toBe(false);
        });

        it("keeps the listed map over for a dropped collection", async () => {
            const wrapper = createTarget({
                multiple: true,
                value: null,
                options: {
                    hdca: [{ id: "hdcaLL", hid: 9, name: "nested", src: "hdca", map_over_type: "list" }],
                },
            });
            await wrapper.vm.$nextTick();
            const before = wrapper.emitted("input")?.length ?? 0;
            eventStore.setDragData({
                id: "hdcaLL",
                hid: 9,
                name: "nested",
                history_content_type: "dataset_collection",
                collection_type: "list:list",
            });
            dispatchEvent(wrapper, "dragenter");
            dispatchEvent(wrapper, "drop");
            expect(emittedArg(wrapper, "input", before)).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLL", map_over_type: "list", src: "hdca" }],
            });
            // no second, unmarked entry for the dropped collection
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            expect(wrapper.findAll(SELECT_OPTIONS).length).toBe(1);
        });

        it("keeps a value mapped over a type no longer listed on a mapped-over entry", async () => {
            const wrapper = createTarget({
                ...nestedListProps,
                value: { values: [{ id: "hdcaLL", src: "hdca", map_over_type: "paired" }] },
            });
            await wrapper.vm.$nextTick();
            expect(emittedArg(wrapper, "input", -1)).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLL", map_over_type: "list", src: "hdca" }],
            });
        });

        it("maps a dropped collection over the deepest accepted type, like the server", async () => {
            const wrapper = createTarget({ ...nestedListProps, options: { hdca: [] }, value: null });
            await wrapper.vm.$nextTick();
            const before = wrapper.emitted("input")?.length ?? 0;
            eventStore.setDragData({
                id: "hdcaLLL",
                hid: 10,
                name: "deep",
                history_content_type: "dataset_collection",
                collection_type: "list:list:list",
            });
            dispatchEvent(wrapper, "dragenter");
            dispatchEvent(wrapper, "drop");
            expect(emittedArg(wrapper, "input", before)).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLLL", map_over_type: "list:list", src: "hdca" }],
            });
        });

        it("uses a dropped collection directly when the input also accepts its type", async () => {
            const wrapper = createTarget({ ...nestedListProps, options: { hdca: [] }, value: null });
            await wrapper.vm.$nextTick();
            const before = wrapper.emitted("input")?.length ?? 0;
            eventStore.setDragData({
                id: "hdcaLL2",
                hid: 11,
                name: "nested2",
                history_content_type: "dataset_collection",
                collection_type: "list:list",
            });
            dispatchEvent(wrapper, "dragenter");
            dispatchEvent(wrapper, "drop");
            expect(emittedArg(wrapper, "input", before)).toEqual({
                batch: false,
                product: false,
                values: [{ id: "hdcaLL2", map_over_type: null, src: "hdca" }],
            });
        });

        it("lets the listed entry replace a dropped collection once its page loads", async () => {
            const wrapper = createTarget({ multiple: true, value: null, options: { hdca: [] } });
            await wrapper.vm.$nextTick();
            eventStore.setDragData({
                id: "hdcaLL",
                hid: 9,
                name: "nested",
                history_content_type: "dataset_collection",
                collection_type: "list:list",
            });
            dispatchEvent(wrapper, "dragenter");
            dispatchEvent(wrapper, "drop");
            const dropped = emittedArg(wrapper, "input", -1);
            await wrapper.setProps({
                value: dropped,
                options: { hdca: [{ id: "hdcaLL", hid: 9, name: "nested", src: "hdca", map_over_type: "list" }] },
            });
            await wrapper.vm.$nextTick();
            expect(emittedArg(wrapper, "input", -1)).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLL", map_over_type: "list", src: "hdca" }],
            });
            await openMultiselect(wrapper);
            const options = wrapper.findAll(SELECT_OPTIONS);
            expect(options.length).toBe(1);
            expect(nth(options, 0).find(MAP_OVER_MARKER).text()).toBe("one job per list");
        });

        it("submits a collection once even when both its entries are selected", async () => {
            const wrapper = createTarget({
                multiple: true,
                options: nestedListProps.options,
                value: {
                    values: [
                        { id: "hdcaLL", src: "hdca" },
                        { id: "hdcaLL", src: "hdca", map_over_type: "list" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            for (const value of allEmitted(wrapper)) {
                expect(value).toEqual({
                    batch: false,
                    product: false,
                    values: [{ id: "hdcaLL", map_over_type: null, src: "hdca" }],
                });
            }
        });

        it("marks map-over entries in the column select", async () => {
            const wrapper = createTarget({
                multiple: true,
                value: { values: [{ id: "hdcaLL", src: "hdca" }] },
                options: {
                    hdca: [
                        { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", map_over_type: "list" },
                        { id: "hdcaL", hid: 8, name: "flat", src: "hdca" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            await wrapper.find("button.ui-link").trigger("click");
            const selected = wrapper.findAll(".options-list:not(.unselected) > button");
            const unselected = wrapper.findAll(".options-list.unselected > button");
            expect(selected.length).toBe(1);
            expect(nth(selected, 0).find(MAP_OVER_MARKER).text()).toBe("one job per list");
            expect(unselected.length).toBe(1);
            expect(nth(unselected, 0).text()).toBe("8: flat");
        });

        it("leaves collections on a dataset input unmarked, the field hint covers them", async () => {
            const wrapper = createTarget({
                value: { values: [{ id: "hdca5", src: "hdca" }] },
                options: { hda: defaultOptions.hda, hdca: defaultOptions.hdca },
            });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            expect(wrapper.findAll(SELECT_OPTIONS).length).toBe(2);
            expect(wrapper.find(".form-data-processing-hint").attributes("data-processing-mode")).toBe("batch");
            expect(wrapper.find(MAP_OVER_MARKER).exists()).toBe(false);
        });

        it("leaves workflow run options unmarked", async () => {
            const wrapper = createTarget({ ...nestedListProps, workflowRun: true, value: null });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            expect(wrapper.findAll(SELECT_OPTIONS).length).toBe(3);
            expect(wrapper.find(MAP_OVER_MARKER).exists()).toBe(false);
        });
    });

    describe("processing hint", () => {
        const PROCESSING_HINT = ".form-data-processing-hint";

        /** Hint text without the mocked help popovers, whitespace collapsed */
        function hintText(wrapper: ReturnType<typeof createTarget>) {
            return wrapper.find(PROCESSING_HINT).text().replaceAll("Mocked Popover", "").replace(/\s+/g, " ").trim();
        }

        const listPairedOptions = {
            hdca: [{ id: "hdcaLP", hid: 7, name: "reads", src: "hdca", map_over_type: "paired" }],
        };

        it("explains mapping a nested collection over a collection input", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                value: { values: [{ id: "hdcaLP", src: "hdca" }] },
                options: listPairedOptions,
            });
            await wrapper.vm.$nextTick();
            expect(emittedArg(wrapper, "input")).toEqual({
                batch: true,
                product: false,
                values: [{ id: "hdcaLP", map_over_type: "paired", src: "hdca" }],
            });
            const hint = wrapper.find(PROCESSING_HINT);
            expect(hint.exists()).toBe(true);
            expect(hintText(wrapper)).toBe(
                "The selected collection will be mapped over this tool: one job per dataset pair.",
            );
        });

        it("names the type of the selected collection when known", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                value: { values: [{ id: "hdcaLP", src: "hdca" }] },
                options: { hdca: [{ ...listPairedOptions.hdca[0], collection_type: "list:paired" }] },
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "The selected list of pairs will be mapped over this tool: one job per dataset pair.",
            );
        });

        it("falls back to raw collection types without a label", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["list:list"],
                value: { values: [{ id: "hdcaLLL", src: "hdca" }] },
                options: {
                    hdca: [
                        {
                            id: "hdcaLLL",
                            hid: 8,
                            name: "deep",
                            src: "hdca",
                            collection_type: "list:list:list",
                            map_over_type: "list:list",
                        },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "The selected list:list:list collection will be mapped over this tool: one job per nested list:list.",
            );
        });

        it("explains each selected dataset of a batch runs separately", async () => {
            const wrapper = createTarget({
                value: {
                    values: [
                        { id: "hda2", src: "hda" },
                        { id: "hda3", src: "hda" },
                    ],
                },
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "Each selected dataset will be run as a separate job, matched in order with other batch inputs.",
            );
        });

        it("describes an optional collection input before anything is selected", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                optional: true,
                value: null,
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe("A collection selected here will be processed as a whole in a single job.");
        });

        it("describes the collection tab of an optional dataset input before anything is selected", async () => {
            const wrapper = createTarget({
                optional: true,
                value: null,
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(wrapper.find(PROCESSING_HINT).exists()).toBe(false);
            await wrapper.find("[title='Dataset collection']").trigger("click");
            expect(hintText(wrapper)).toBe(
                "A collection selected here will be mapped over this tool: one job per dataset.",
            );
        });

        it("explains several collections are processed together in a single job", async () => {
            const wrapper = createTarget({
                value: {
                    values: [
                        { id: "hdca5", src: "hdca" },
                        { id: "hdca6", src: "hdca" },
                    ],
                },
                multiple: true,
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "The selected collections will be processed together in a single job. Need one job per element?",
            );
        });

        it("explains a collection mapped over a dataset input", async () => {
            const wrapper = createTarget({
                value: { values: [{ id: "hdca5", src: "hdca" }] },
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(wrapper.find(PROCESSING_HINT).attributes("data-processing-mode")).toBe("batch");
            expect(hintText(wrapper)).toBe(
                "The selected collection will be mapped over this tool: one job per dataset.",
            );
        });

        it("explains a directly matching collection is processed in a single job", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                value: { values: [{ id: "hdca5", src: "hdca" }] },
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            const hint = wrapper.find(PROCESSING_HINT);
            expect(hint.attributes("data-processing-mode")).toBe("bulk");
            // nesting cannot split a pair, so no hint on running per element
            expect(hintText(wrapper)).toBe("The selected collection will be processed as a whole in a single job.");
        });

        it("explains multiple datasets are processed together in a single job", async () => {
            const wrapper = createTarget({
                value: {
                    values: [
                        { id: "hda2", src: "hda" },
                        { id: "hda3", src: "hda" },
                    ],
                },
                multiple: true,
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            const hint = wrapper.find(PROCESSING_HINT);
            expect(hint.attributes("data-processing-mode")).toBe("bulk");
            expect(hintText(wrapper)).toBe(
                "All selected datasets will be processed together in a single job. Need one job per dataset?",
            );
        });

        it("says nothing about a single dataset in a single dataset input", async () => {
            const wrapper = createTarget({
                value: { values: [{ id: "hda2", src: "hda" }] },
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(wrapper.find(PROCESSING_HINT).exists()).toBe(false);
        });

        it("says nothing when there is nothing to select", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                value: null,
                options: {},
            });
            await wrapper.vm.$nextTick();
            expect(wrapper.find(".form-data-no-options-alert").exists()).toBe(true);
            expect(wrapper.find(PROCESSING_HINT).exists()).toBe(false);
        });

        it("leaves workflow run inputs to their own batch controls", async () => {
            for (const props of [{ workflowRun: true }, { flavor: "module" }]) {
                const wrapper = createTarget({
                    ...props,
                    type: "data_collection",
                    collectionTypes: ["paired"],
                    value: { values: [{ id: "hdcaLP", src: "hdca" }] },
                    options: listPairedOptions,
                });
                await wrapper.vm.$nextTick();
                expect(wrapper.find(PROCESSING_HINT).exists()).toBe(false);
            }
        });

        it("agrees with the submitted batch flag", async () => {
            const cases: Array<Record<string, unknown>> = [
                { value: { values: [{ id: "hda2", src: "hda" }] } },
                { value: { values: [{ id: "hdca5", src: "hdca" }] } },
                { value: { values: [{ id: "dce2", src: "dce" }] } },
                { value: { values: [{ id: "dce3", src: "dce" }] } },
                { value: { values: [{ id: "dce3", src: "dce" }] }, type: "data_collection" },
                { value: { values: [{ id: "hdca5", src: "hdca" }] }, type: "data_collection" },
                { value: { values: [{ id: "hdca5", src: "hdca" }] }, multiple: true },
                { ...nestedListProps, value: { values: [{ id: "hdcaLL", src: "hdca" }] } },
                { ...nestedListProps, value: { values: [{ id: "hdcaLL", src: "hdca", map_over_type: "list" }] } },
                {
                    value: {
                        values: [
                            { id: "hda2", src: "hda" },
                            { id: "hda3", src: "hda" },
                        ],
                    },
                    multiple: true,
                },
                {
                    value: {
                        values: [
                            { id: "dce1", src: "dce" },
                            { id: "dce4", src: "dce" },
                        ],
                    },
                },
            ];
            for (const props of cases) {
                const wrapper = createTarget({ options: defaultOptions, ...props });
                await wrapper.vm.$nextTick();
                const emitted = emittedArg(wrapper, "input", wrapper.emitted("input")!.length - 1) as {
                    batch: boolean;
                };
                const hint = wrapper.find(PROCESSING_HINT);
                const mode = hint.exists() ? hint.attributes("data-processing-mode") : undefined;
                expect(mode === "batch", JSON.stringify(props)).toBe(emitted.batch);
            }
        });
    });

    it("tagging filter", async () => {
        const wrapper_0 = createTarget({
            tag: "tag1",
            options: defaultOptions,
        });
        await openMultiselect(wrapper_0);
        const select_0 = wrapper_0.findAll(SELECT_OPTIONS);
        expect(select_0.length).toBe(4);
        expect(nth(select_0, 2).text()).toContain("1: hdaName1");
        expect(nth(select_0, 3).text()).toContain("2: hdaName2");
        const wrapper_1 = createTarget({
            tag: "tag2",
            options: defaultOptions,
        });
        await openMultiselect(wrapper_1);
        const select_1 = wrapper_1.findAll(SELECT_OPTIONS);
        expect(select_1.length).toBe(4);
        expect(nth(select_1, 2).text()).toContain("2: hdaName2");
        expect(nth(select_1, 3).text()).toContain("3: hdaName3");
        const wrapper_2 = createTarget({
            tag: "tag3",
            options: defaultOptions,
        });
        await openMultiselect(wrapper_2);
        const select_2 = wrapper_2.findAll(SELECT_OPTIONS);
        expect(select_2.length).toBe(3);
        expect(nth(select_2, 2).text()).toContain("3: hdaName3");
    });
});
