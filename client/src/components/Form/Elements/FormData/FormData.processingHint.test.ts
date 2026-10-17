import "@tests/vitest/mockHelpPopovers";
import "@/composables/__mocks__/filter";
import "../FormSelectMany/worker/__mocks__/selectMany";

import { emittedArg } from "@tests/vitest/helpers";
import { describe, expect, it, vi } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";
import { typesAndMappingResponse } from "@/components/Datatypes/test_fixtures";

import { createTarget, defaultOptions, nestedListProps } from "./testData/formDataHarness";

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

        it("names nested list types", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired"],
                value: { values: [{ id: "hdcaLLP", src: "hdca" }] },
                options: {
                    hdca: [
                        {
                            id: "hdcaLLP",
                            hid: 8,
                            name: "nested reads",
                            src: "hdca",
                            collection_type: "list:list:paired",
                            map_over_type: "paired",
                        },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "The selected list of lists of pairs will be mapped over this tool: one job per dataset pair.",
            );
        });

        it("names a nested list mapped over a list input", async () => {
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
                "The selected list:list:list collection will be mapped over this tool: one job per list of lists.",
            );
        });

        it("falls back to raw collection types without a label", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["list:list:list"],
                value: { values: [{ id: "hdcaLLLL", src: "hdca" }] },
                options: {
                    hdca: [
                        {
                            id: "hdcaLLLL",
                            hid: 8,
                            name: "deepest",
                            src: "hdca",
                            collection_type: "list:list:list:list",
                            map_over_type: "list:list:list",
                        },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe(
                "The selected list:list:list:list collection will be mapped over this tool: one job per nested list:list:list.",
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

        it("runs one job per selected collection when several are batched", async () => {
            // the server only splits a collection when it is the sole batch value
            const wrapper = createTarget({
                multiple: true,
                value: {
                    values: [
                        { id: "hdcaLL", src: "hdca", map_over_type: "list" },
                        { id: "hdcaL", src: "hdca" },
                    ],
                },
                options: {
                    hdca: [
                        { id: "hdcaLL", hid: 9, name: "nested", src: "hdca", map_over_type: "list" },
                        { id: "hdcaL", hid: 8, name: "flat", src: "hdca" },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            expect(emittedArg(wrapper, "input", -1)).toMatchObject({ batch: true });
            expect(hintText(wrapper)).toBe(
                "Each selected collection will be run as a separate job, matched in order with other batch inputs.",
            );
        });

        it("explains a plain list mapped over a paired_or_unpaired input one dataset at a time", async () => {
            const wrapper = createTarget({
                type: "data_collection",
                collectionTypes: ["paired_or_unpaired"],
                value: { values: [{ id: "hdcaL", src: "hdca" }] },
                options: {
                    hdca: [
                        {
                            id: "hdcaL",
                            hid: 6,
                            name: "singles",
                            src: "hdca",
                            collection_type: "list",
                            map_over_type: "single_datasets",
                        },
                    ],
                },
            });
            await wrapper.vm.$nextTick();
            expect(hintText(wrapper)).toBe("The selected list will be mapped over this tool: one job per dataset.");
        });

        it("says nothing about a single dataset in a single dataset input", async () => {
            const wrapper = createTarget({
                value: { values: [{ id: "hda2", src: "hda" }] },
                options: defaultOptions,
            });
            await wrapper.vm.$nextTick();
            expect(wrapper.find(PROCESSING_HINT).exists()).toBe(false);
            // the same dataset in the multiple datasets field is batched
            await wrapper.find("[title='Multiple datasets']").trigger("click");
            expect(wrapper.find(PROCESSING_HINT).attributes("data-processing-mode")).toBe("batch");
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
            await wrapper.setProps({ options: listPairedOptions });
            expect(wrapper.find(".form-data-no-options-alert").exists()).toBe(false);
            expect(wrapper.find(PROCESSING_HINT).exists()).toBe(true);
        });

        it("leaves workflow run inputs to their own batch controls", async () => {
            const cases: Array<[Record<string, unknown>, boolean]> = [
                [{}, true],
                [{ workflowRun: true }, false],
                [{ flavor: "module" }, false],
            ];
            for (const [props, showsHint] of cases) {
                const wrapper = createTarget({
                    ...props,
                    type: "data_collection",
                    collectionTypes: ["paired"],
                    value: { values: [{ id: "hdcaLP", src: "hdca" }] },
                    options: listPairedOptions,
                });
                await wrapper.vm.$nextTick();
                expect(wrapper.find(PROCESSING_HINT).exists(), JSON.stringify(props)).toBe(showsHint);
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
});
