import { getLocalVue } from "@tests/vitest/helpers";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import type { HDASummary } from "@/api";
import { useServerMock } from "@/api/client/__mocks__";
import type { MyHistory } from "@/api/histories";

import HistoryDatasetPicker from "./HistoryDatasetPicker.vue";

const { server, http } = useServerMock();

const HISTORY: MyHistory = {
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

const DATASET: HDASummary = {
    id: "d1",
    name: "1.txt",
    create_time: "2026-01-01T00:00:00",
    dataset_id: "ds1",
    deleted: false,
    extension: "txt",
    genome_build: "?",
    hid: 1,
    history_content_type: "dataset",
    history_id: "h1",
    purged: false,
    state: "ok",
    tags: [],
    type: "file",
    update_time: "2026-01-02T00:00:00",
    url: "/api/datasets/d1",
    visible: true,
};

function interceptHistories() {
    const queries: Record<string, string>[] = [];
    server.use(
        http.get("/api/histories", ({ request, response }) => {
            queries.push(Object.fromEntries(new URL(request.url).searchParams.entries()));
            return response(200).json([HISTORY], { headers: { total_matches: "1" } });
        }),
    );
    return queries;
}

function interceptDatasets() {
    server.use(
        http.get("/api/datasets", ({ response }) => {
            return response(200).json([DATASET], { headers: { total_matches: "1" } });
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
