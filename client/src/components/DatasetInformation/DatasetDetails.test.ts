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

import DatasetDetails from "./DatasetDetails.vue";

vi.mock("@/composables/config");

// Stubbed by module: as <script setup> imports they can't be stubbed by name, and the real ones fetch more.
type StubProps = { dataset?: { file_size?: number } };

function stubComponent(name: string, render?: (props: StubProps) => string) {
    return {
        default: {
            name,
            props: ["dataset", "datasetId", "jobId", "datasetName", "dependencies"],
            render(this: { $props: StubProps }, h: (tag: string, data: object, text?: string) => unknown) {
                return h("div", { class: name }, render?.(this.$props));
            },
        },
    };
}
vi.mock("@/components/DatasetInformation/DatasetInformation.vue", () =>
    stubComponent("DatasetInformation", (props) => `size ${props.dataset?.file_size}`),
);
vi.mock("@/components/Dataset/DatasetStorage/DatasetStorage.vue", () => stubComponent("DatasetStorage"));
vi.mock("@/components/InheritanceChain//InheritanceChain.vue", () => stubComponent("InheritanceChain"));
vi.mock("@/components/JobDependencies/JobDependencies.vue", () => stubComponent("JobDependencies"));
vi.mock("@/components/JobDestinationParams/JobDestinationParams.vue", () => stubComponent("JobDestinationParams"));
vi.mock("@/components/JobInformation/JobInformation.vue", () => stubComponent("JobInformation"));
vi.mock("@/components/JobMetrics/JobMetrics.vue", () => stubComponent("JobMetrics"));
vi.mock("@/components/JobParameters/JobParameters.vue", () => stubComponent("JobParameters"));

const DATASET_ID = "dataset_id";
const JOB_ID = "job_id";

const localVue = getLocalVue();
const { server, http } = useServerMock();

const dataset = {
    id: DATASET_ID,
    name: "Test Dataset",
    state: "ok",
    file_ext: "txt",
    file_size: 100,
    peek: "<pre>first peek</pre>",
    creating_job: JOB_ID,
    update_time: "2026-01-01T00:00:00",
};

function serveDataset(served: object) {
    server.use(
        http.untyped.get("/api/datasets/:dataset_id", () => {
            return HttpResponse.json(served);
        }),
        http.untyped.get("/api/jobs/:job_id", () => {
            return HttpResponse.json({ id: JOB_ID, state: "ok" });
        }),
    );
}

/** Store the dataset with a new update time, the way the history watcher reports a change. */
function storeUpdate(updateTime: string) {
    useDatasetStore().storedDatasets = {
        [DATASET_ID]: { ...dataset, update_time: updateTime } as unknown as HDADetailed,
    };
}

async function mountDatasetDetails() {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
    setActivePinia(pinia);
    const wrapper = mount(DatasetDetails as object, {
        propsData: { datasetId: DATASET_ID },
        localVue,
        pinia,
    });
    await flushPromises();
    return wrapper;
}

describe("DatasetDetails", () => {
    it("shows the dataset, its job and its peek", async () => {
        serveDataset(dataset);
        const wrapper = await mountDatasetDetails();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 100");
        expect(wrapper.find(".JobInformation").exists()).toBe(true);
        expect(wrapper.find(".dataset-peek").text()).toBe("first peek");
        expect(wrapper.text()).not.toContain("Job Not Found");
    });

    it("explains a dataset without a creating job", async () => {
        serveDataset({ ...dataset, creating_job: null });
        const wrapper = await mountDatasetDetails();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 100");
        expect(wrapper.find(".JobInformation").exists()).toBe(false);
        expect(wrapper.text()).toContain("Job Not Found");
    });

    it("refreshes the details in place when the dataset is updated", async () => {
        serveDataset(dataset);
        const wrapper = await mountDatasetDetails();
        storeUpdate(dataset.update_time);
        await flushPromises();

        const { released, release } = hold();
        server.use(
            http.untyped.get("/api/datasets/:dataset_id", async () => {
                await released;
                return HttpResponse.json({ ...dataset, file_size: 200, peek: "<pre>new peek</pre>" });
            }),
        );
        storeUpdate("2026-01-01T00:05:00");
        await flushPromises();
        expect(wrapper.text()).not.toContain("Loading dataset details");
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 100");

        release();
        await flushPromises();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 200");
        expect(wrapper.find(".dataset-peek").text()).toBe("new peek");
    });

    it("keeps the last details when refreshing them fails", async () => {
        serveDataset(dataset);
        const wrapper = await mountDatasetDetails();
        storeUpdate(dataset.update_time);
        await flushPromises();

        server.use(
            http.untyped.get("/api/datasets/:dataset_id", () => {
                return HttpResponse.json({ err_msg: "refresh failed" }, { status: 500 });
            }),
        );
        storeUpdate("2026-01-01T00:05:00");
        await flushPromises();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 100");
        expect(wrapper.find(".dataset-peek").text()).toBe("first peek");
        expect(wrapper.find(".dataset-details-refresh-error").text()).toContain("refresh failed");

        serveDataset({ ...dataset, file_size: 200 });
        storeUpdate("2026-01-01T00:10:00");
        await flushPromises();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 200");
        expect(wrapper.find(".dataset-details-refresh-error").exists()).toBe(false);
    });

    it("ignores a refresh that finishes after a newer one", async () => {
        serveDataset(dataset);
        const wrapper = await mountDatasetDetails();
        storeUpdate(dataset.update_time);
        await flushPromises();

        const { released, release } = hold();
        let fetches = 0;
        server.use(
            http.untyped.get("/api/datasets/:dataset_id", async () => {
                fetches += 1;
                if (fetches === 1) {
                    await released;
                    return HttpResponse.json({ ...dataset, file_size: 200 });
                }
                return HttpResponse.json({ ...dataset, file_size: 300 });
            }),
        );
        storeUpdate("2026-01-01T00:05:00");
        await flushPromises();
        storeUpdate("2026-01-01T00:10:00");
        await flushPromises();
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 300");

        release();
        await flushPromises();
        expect(fetches).toBe(2);
        expect(wrapper.find(".DatasetInformation").text()).toBe("size 300");
    });
});
