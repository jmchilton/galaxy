import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { defineComponent, h } from "vue";

import { useServerMock } from "@/api/client/__mocks__";
import type { AnyFetchTarget, UrlDataElement } from "@/api/tools";

import FetchGrid from "./FetchGrid.vue";

// Stub only the grid itself, so the test renders it through useAgGrid's async wrapper like the app does.
vi.mock("ag-grid-vue3", () => ({
    AgGridVue: defineComponent({
        name: "AgGridVue",
        props: {
            modelValue: { type: Array, default: undefined },
            rowData: { type: Array, default: undefined },
        },
        emits: ["update:modelValue", "cellValueChanged"],
        render() {
            return h("div");
        },
    }),
}));

const localVue = getLocalVue(true);

const { server, http } = useServerMock();
beforeEach(() => {
    server.use(
        http.get("/api/configuration", ({ response }) => response(200).json({})),
        http.get("/api/genomes", ({ response }) => response(200).json([])),
        http.get("/api/datatypes", ({ response }) => response(200).json([])),
    );
});

const TARGET = {
    destination: { type: "hdas" },
    elements: [{ src: "url", name: "file1.txt", url: "http://example.com/file1.txt", ext: "txt", dbkey: "?" }],
    auto_decompress: false,
} as unknown as AnyFetchTarget;

describe("FetchGrid", () => {
    it("builds its request from the rows as edited in the grid", async () => {
        const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
        setActivePinia(pinia);
        const wrapper = mount(FetchGrid, { props: { target: TARGET }, global: withPlugins(localVue, pinia) });
        await flushPromises();

        // AG Grid edits its own copies of the rows, then reports them through v-model.
        const grid = wrapper.findComponent({ name: "AgGridVue" });
        const props = grid.props() as { modelValue?: object[]; rowData?: object[] };
        const rows = JSON.parse(JSON.stringify(props.modelValue ?? props.rowData)) as Record<string, unknown>[];
        const nameKey = Object.keys(rows[0]!).find((key) => rows[0]![key] === "file1.txt")!;
        rows[0]![nameKey] = "renamed.txt";
        grid.vm.$emit("update:modelValue", Object.freeze(rows));
        grid.vm.$emit("cellValueChanged", {});
        await flushPromises();

        const target = (wrapper.vm as unknown as { asTarget: () => { elements: UrlDataElement[] } }).asTarget();
        expect(target.elements[0]!.name).toBe("renamed.txt");
    });
});
