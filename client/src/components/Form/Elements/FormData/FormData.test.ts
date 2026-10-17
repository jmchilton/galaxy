import "@tests/vitest/mockHelpPopovers";
import "@/composables/__mocks__/filter";
import "../FormSelectMany/worker/__mocks__/selectMany";

import { dispatchEvent, emittedArg, nth } from "@tests/vitest/helpers";
import { describe, expect, it, vi } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";
import { typesAndMappingResponse } from "@/components/Datatypes/test_fixtures";

import {
    createTarget,
    defaultOptions,
    eventStore,
    nestedListProps,
    openMultiselect,
    SELECT_OPTIONS,
    SELECTED_VALUE,
} from "./testData/formDataHarness";

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

    it("names nested collection types in the no-options alert", async () => {
        const wrapper = createTarget({
            type: "data_collection",
            collectionTypes: ["list:list", "list:list:paired"],
            value: null,
            options: {},
        });
        expect(wrapper.find(".form-data-no-options-alert").text()).toBe(
            "No list of lists or list of lists of pairs dataset collections available",
        );
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

    it("maps a dropped collection element over the input when its child collection is nested deeper", async () => {
        const wrapper = createTarget({
            type: "data_collection",
            collectionTypes: ["list"],
            options: { hdca: [] },
            value: null,
        });
        await wrapper.vm.$nextTick();
        const before = wrapper.emitted("input")?.length ?? 0;
        eventStore.setDragData({
            id: "dceLL",
            element_identifier: "inner",
            element_type: "dataset_collection",
            object: { id: "childLL", collection_type: "list:list" },
        } as any);
        dispatchEvent(wrapper, "dragenter");
        dispatchEvent(wrapper, "drop");
        expect(emittedArg(wrapper, "input", before)).toEqual({
            batch: true,
            product: false,
            values: [{ id: "dceLL", map_over_type: "list", src: "dce" }],
        });
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
        const emitted = (wrapper.emitted("input") ?? []).map((args) => args[0]);
        expect(emitted.length).toBeGreaterThan(0);
        for (const value of emitted) {
            expect(value).toEqual({
                batch: false,
                product: false,
                values: [{ id: "hdcaLL", map_over_type: null, src: "hdca" }],
            });
        }
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
