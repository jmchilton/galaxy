import { getLocalVue } from "@tests/vitest/helpers";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";

import HistoryDatasetPicker from "./HistoryDatasetPicker.vue";

const { server, http } = useServerMock();

const HISTORY = {
    id: "h1",
    name: "Recent History",
    model_class: "History",
    annotation: null,
    archived: false,
    count: 3,
    deleted: false,
    published: false,
    purged: false,
    tags: [],
    update_time: "2026-01-02T00:00:00",
    url: "/api/histories/h1",
    username: "test-user",
};

const DATASET = {
    id: "d1",
    name: "1.txt",
    history_content_type: "dataset",
    update_time: "2026-01-02T00:00:00",
    url: "/api/datasets/d1",
};

function interceptHistories() {
    const queries: Record<string, string>[] = [];
    server.use(
        http.get("/api/histories", ({ request, response }) => {
            queries.push(Object.fromEntries(new URL(request.url).searchParams.entries()));
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            return response(200).json([HISTORY] as any, { headers: { total_matches: "1" } });
        }),
    );
    return queries;
}

function interceptDatasets() {
    server.use(
        http.get("/api/datasets", ({ response }) => {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            return response(200).json([DATASET] as any, { headers: { total_matches: "1" } });
        }),
    );
}

async function mountPicker() {
    const wrapper = mount(HistoryDatasetPicker as object, { global: getLocalVue() });
    await flushPromises();
    return wrapper;
}

describe("HistoryDatasetPicker", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
    });

    it("lists only the user's own histories, most recently updated first", async () => {
        const queries = interceptHistories();

        const wrapper = await mountPicker();

        expect(queries[0]).toMatchObject({
            search: "",
            sort_by: "update_time",
            sort_desc: "true",
            show_own: "true",
            show_published: "false",
            show_shared: "false",
            show_archived: "false",
        });
        expect(wrapper.text()).toContain("Recent History");
    });

    it("keeps the history list newest first after sorting a history's datasets", async () => {
        const queries = interceptHistories();
        interceptDatasets();
        const wrapper = await mountPicker();

        await wrapper.find(".selection-dialog-folder").trigger("click");
        await flushPromises();
        await wrapper.find("th.g-table-sortable").trigger("click");
        await flushPromises();
        await wrapper.find("[data-description='selection dialog undo']").trigger("click");
        await flushPromises();

        expect(queries.length).toBeGreaterThan(1);
        expect(queries[queries.length - 1]).toMatchObject({ sort_by: "update_time", sort_desc: "true" });
    });
});
