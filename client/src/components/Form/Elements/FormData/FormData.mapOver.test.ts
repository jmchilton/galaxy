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
                        { id: "hdcaLLLP", hid: 4, name: "deeper", src: "hdca", map_over_type: "list:list:paired" },
                        { id: "hdcaLLLL", hid: 3, name: "deepest", src: "hdca", map_over_type: "list:list:list" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            const markers = wrapper.findAll(MAP_OVER_MARKER).map((marker) => marker.text());
            expect(markers).toEqual([
                "one job per dataset pair",
                "one job per dataset",
                "one job per list of lists",
                "one job per list of lists of pairs",
                "one job per nested list:list:list",
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
            const toolForm = createTarget({ ...nestedListProps, value: null });
            await toolForm.vm.$nextTick();
            await openMultiselect(toolForm);
            expect(toolForm.find(MAP_OVER_MARKER).exists()).toBe(true);

            const wrapper = createTarget({ ...nestedListProps, workflowRun: true, value: null });
            await wrapper.vm.$nextTick();
            await openMultiselect(wrapper);
            expect(wrapper.findAll(SELECT_OPTIONS).length).toBe(3);
            expect(wrapper.find(MAP_OVER_MARKER).exists()).toBe(false);
        });
    });
});
