import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { hold } from "@tests/vitest/hold";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { describe, expect, it, vi } from "vitest";

import type { HDADetailed } from "@/api";
import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useDatasetStore } from "@/stores/datasetStore";

import DatasetAttributes from "./DatasetAttributes.vue";

const DATASET_ID = "dataset_id";

const localVue = getLocalVue();
const { server, http } = useServerMock();

async function mountDatasetAttributes(conversion_disable = false) {
    const pinia = createTestingPinia({ createSpy: vi.fn });
    setActivePinia(pinia);

    server.use(
        http.untyped.put("/dataset/set_edit", () => {
            return HttpResponse.json({ message: "success", status: "success" });
        }),
        http.untyped.get("/dataset/get_edit", ({ request }) => {
            const url = new URL(request.url);
            if (url.searchParams.get("dataset_id") === DATASET_ID) {
                return HttpResponse.json({
                    attribute_inputs: [{ name: "attribute_text", type: "text" }],
                    conversion_inputs: [{ name: "conversion_text", type: "text" }],
                    conversion_disable: conversion_disable,
                    datatype_inputs: [{ name: "datatype_text", type: "text" }],
                    permission_inputs: [{ name: "permission_text", type: "text" }],
                });
            }
            return HttpResponse.json({}, { status: 404 });
        }),
    );

    const wrapper = mount(DatasetAttributes as object, {
        propsData: {
            datasetId: DATASET_ID,
        },
        localVue,
        pinia,
    });

    await flushPromises();

    return wrapper;
}

function storeDataset(updateTime: string) {
    useDatasetStore().storedDatasets = { [DATASET_ID]: { id: DATASET_ID, update_time: updateTime } as HDADetailed };
}

async function buildWrapperWithError(error: string) {
    server.use(
        http.untyped.get("/dataset/get_edit", () => {
            return HttpResponse.json({}, { status: 400 });
        }),
    );
    const wrapper = mount(DatasetAttributes as object, {
        propsData: {
            datasetId: DATASET_ID,
            messageText: error,
            messageVariant: "danger",
        },
        localVue,
        stubs: {
            FontAwesomeIcon: false,
            FormElement: false,
        },
    });
    await flushPromises();
    return wrapper;
}

describe("DatasetAttributes", () => {
    it("check rendering", async () => {
        const wrapper = await mountDatasetAttributes();

        expect(wrapper.findAll("button").length).toBe(6);
        expect(wrapper.findAll("#attribute_text").length).toBe(1);
        expect(wrapper.findAll("#conversion_text").length).toBe(1);
        expect(wrapper.findAll("#datatype_text").length).toBe(1);
        expect(wrapper.findAll("#permission_text").length).toBe(1);
        expect(wrapper.findAll(".tab-pane").length).toBe(3);
        expect(wrapper.findAll(".ui-portlet-section").length).toBe(2);

        const saveButton = wrapper.find("#dataset-attributes-default-save");

        await saveButton.trigger("click");

        await flushPromises();

        expect(wrapper.find("[role=alert]").text()).toBe("success");
    });

    it("shows why saving failed", async () => {
        const wrapper = await mountDatasetAttributes();
        server.use(
            http.untyped.put("/dataset/set_edit", () => {
                return HttpResponse.json({ err_msg: "This dataset is encrypted." }, { status: 400 });
            }),
        );

        await wrapper.find("#dataset-attributes-default-save").trigger("click");
        await flushPromises();

        expect(wrapper.find(".dataset-attributes-alert").text()).toBe("This dataset is encrypted.");
    });

    it("check rendering without conversion option", async () => {
        const wrapper = await mountDatasetAttributes(true);

        expect(wrapper.findAll("button").length).toBe(5);
        expect(wrapper.findAll("#attribute_text").length).toBe(1);
        expect(wrapper.findAll("#conversion_text").length).toBe(0);
        expect(wrapper.findAll("#datatype_text").length).toBe(1);
        expect(wrapper.findAll("#permission_text").length).toBe(1);
        expect(wrapper.findAll(".tab-pane").length).toBe(3);
        expect(wrapper.findAll(".ui-portlet-section").length).toBe(1);
    });

    it("reloads the forms after a save so new datatype metadata appears", async () => {
        const wrapper = await mountDatasetAttributes();
        expect(wrapper.findAll("#attribute_chromCol").length).toBe(0);

        server.use(
            http.untyped.get("/dataset/get_edit", () => {
                return HttpResponse.json({
                    attribute_inputs: [
                        { name: "attribute_text", type: "text" },
                        { name: "attribute_chromCol", type: "text", value: "1" },
                    ],
                    conversion_inputs: [{ name: "conversion_text", type: "text" }],
                    datatype_inputs: [{ name: "datatype_text", type: "text" }],
                    permission_inputs: [{ name: "permission_text", type: "text" }],
                });
            }),
        );
        await wrapper.find("#dataset-attributes-default-save").trigger("click");
        await flushPromises();

        expect(wrapper.findAll("#attribute_chromCol").length).toBe(1);
        expect(wrapper.find("[role=alert]").text()).toBe("success");

        let submitted: Record<string, unknown> | undefined;
        server.use(
            http.untyped.put("/dataset/set_edit", async ({ request }) => {
                submitted = (await request.json()) as Record<string, unknown>;
                return HttpResponse.json({ message: "success", status: "success" });
            }),
        );
        await wrapper.find("#dataset-attributes-default-save").trigger("click");
        await flushPromises();

        expect(submitted).toHaveProperty("attribute_chromCol", "1");
    });

    it("reloads the forms when the stored dataset is updated", async () => {
        const wrapper = await mountDatasetAttributes();
        storeDataset("2026-01-01T00:00:00");
        await flushPromises();

        server.use(
            http.untyped.get("/dataset/get_edit", () => {
                return HttpResponse.json({
                    attribute_inputs: [{ name: "attribute_chromCol", type: "text" }],
                });
            }),
        );
        // A set-metadata job finishing in the background shows up as a newer update_time.
        storeDataset("2026-01-01T00:00:05");
        await flushPromises();

        expect(wrapper.findAll("#attribute_chromCol").length).toBe(1);
    });

    it("ignores reloaded forms that arrive after newer ones", async () => {
        const wrapper = await mountDatasetAttributes();
        storeDataset("2026-01-01T00:00:00");
        await flushPromises();

        const { released, release } = hold();
        let reloads = 0;
        server.use(
            http.untyped.get("/dataset/get_edit", async () => {
                reloads += 1;
                if (reloads === 1) {
                    await released;
                    return HttpResponse.json({ attribute_inputs: [{ name: "attribute_older", type: "text" }] });
                }
                return HttpResponse.json({ attribute_inputs: [{ name: "attribute_newer", type: "text" }] });
            }),
        );
        storeDataset("2026-01-01T00:00:05");
        await flushPromises();
        await wrapper.find("#dataset-attributes-default-save").trigger("click");
        await flushPromises();
        expect(wrapper.findAll("#attribute_newer").length).toBe(1);

        release();
        await flushPromises();
        expect(reloads).toBe(2);
        expect(wrapper.findAll("#attribute_newer").length).toBe(1);
        expect(wrapper.findAll("#attribute_older").length).toBe(0);
    });

    it("keeps the forms when reloading them after a save fails", async () => {
        const wrapper = await mountDatasetAttributes();

        server.use(
            http.untyped.get("/dataset/get_edit", () => {
                return HttpResponse.json({ err_msg: "reload failed" }, { status: 500 });
            }),
        );
        await wrapper.find("#dataset-attributes-default-save").trigger("click");
        await flushPromises();

        expect(wrapper.find("[role=alert]").text()).toBe("reload failed");
        expect(wrapper.findAll("#attribute_text").length).toBe(1);
        expect(wrapper.findAll("button").length).toBe(6);
    });

    it("doesn't render edit controls with error", async () => {
        const wrapper = await buildWrapperWithError("error");
        expect(wrapper.findAll("button").length).toBe(0);
        expect(wrapper.findAll("#attribute_text").length).toBe(0);
        expect(wrapper.findAll("#conversion_text").length).toBe(0);
        expect(wrapper.findAll("#datatype_text").length).toBe(0);
        expect(wrapper.findAll("#permission_text").length).toBe(0);
        expect(wrapper.findAll(".tab-pane").length).toBe(0);
        expect(wrapper.findAll(".ui-portlet-section").length).toBe(0);
    });
});
