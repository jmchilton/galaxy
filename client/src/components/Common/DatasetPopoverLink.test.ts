import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount, RouterLinkStub, shallowMount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import DatasetPopoverLink from "./DatasetPopoverLink.vue";
import GPopover from "@/components/BaseComponents/GPopover.vue";

const RETRY_BACKOFF_CAP_MS = 30_000;

const { server, http } = useServerMock();

const DATASET_ID = "dataset-id-1";
const POPOVER_STUB = { name: "GPopoverStub", template: "<div><slot /></div>" };
const HISTORY_ID = "history-id-1";
const DATASET = { id: DATASET_ID, history_id: HISTORY_ID, name: "my dataset", peek: "", state: "ok" };

function mountLink(storedDatasets = {}) {
    const wrapper = shallowMount(DatasetPopoverLink as object, {
        props: { datasetId: "dataset_id" },
        global: {
            plugins: [createTestingPinia({ createSpy: vi.fn, initialState: { datasetStore: { storedDatasets } } })],
            stubs: { RouterLink: true, ItemPopoverLink: false },
        },
    });
    return wrapper.findComponent(GPopover);
}

describe("DatasetPopoverLink", () => {
    it("lets keyboard users reach the links in the dataset details", () => {
        expect(mountLink().props("interactive")).toBe(true);
    });

    it("names the details dialog by the dataset rather than its encoded id", () => {
        expect(mountLink().props("ariaLabel")).toBe("Dataset details");
        expect(mountLink({ dataset_id: { id: "dataset_id", name: "reads.fastq" } }).props("ariaLabel")).toBe(
            "reads.fastq",
        );
    });
});

describe("DatasetPopoverLink link wiring", () => {
    function mountWithRouterLinkStub() {
        return shallowMount(DatasetPopoverLink as object, {
            props: { datasetId: DATASET_ID },
            global: {
                plugins: [createTestingPinia({ createSpy: vi.fn })],
                stubs: { RouterLink: RouterLinkStub, ItemPopoverLink: false },
            },
        });
    }

    it("targets the popover at the link's DOM id", () => {
        const wrapper = mountWithRouterLinkStub();
        const linkId = wrapper.findComponent(RouterLinkStub).attributes("id");
        expect(linkId).toBeTruthy();
        expect(wrapper.findComponent(GPopover).props("target")).toBe(linkId);
    });

    it("shows the dataset id and routes to the dataset details", () => {
        const link = mountWithRouterLinkStub().findComponent(RouterLinkStub);
        expect(link.text()).toBe(DATASET_ID);
        expect(link.props("to")).toBe(`/datasets/${DATASET_ID}/details`);
    });
});

describe("DatasetPopoverLink loading", () => {
    let datasetRequests: number;
    let historyRequests: number;
    let failNext: number;
    let wrapper: VueWrapper | undefined;

    beforeEach(() => {
        datasetRequests = 0;
        historyRequests = 0;
        failNext = 0;
        server.use(
            http.get("/api/datasets/{dataset_id}", ({ response }) => {
                datasetRequests++;
                if (failNext > 0) {
                    failNext--;
                    return response("5XX").json({ err_msg: "unavailable", err_code: 0 }, { status: 503 });
                }
                return response.untyped(HttpResponse.json(DATASET));
            }),
            http.get("/api/histories/{history_id}", ({ response }) => {
                historyRequests++;
                return response.untyped(HttpResponse.json({ id: HISTORY_ID, name: "my history" }));
            }),
        );
    });

    afterEach(() => {
        wrapper?.unmount();
        vi.useRealTimers();
    });

    /** Mounts with a GPopover stub that always renders its content. */
    function mountWithServer() {
        const localVue = getLocalVue();
        wrapper = mount(DatasetPopoverLink as object, {
            props: { datasetId: DATASET_ID },
            global: { ...localVue, stubs: { ...localVue.stubs, RouterLink: RouterLinkStub, GPopover: POPOVER_STUB } },
        });
        return wrapper;
    }

    it("does not fetch the dataset before hover", async () => {
        mountWithServer();
        await flushPromises();
        expect(datasetRequests).toBe(0);
        expect(historyRequests).toBe(0);
    });

    it("loads and displays dataset details on hover", async () => {
        const link = mountWithServer();
        await link.findComponent(RouterLinkStub).trigger("mouseenter");
        link.findComponent(POPOVER_STUB).vm.$emit("shown");
        await flushPromises();
        expect(datasetRequests).toBe(1);
        expect(link.find("#dataset-details").exists()).toBe(true);
        expect(link.find(".dataset-details-popover").text()).not.toContain("Loading dataset details");
    });

    it("shows loading during a retry backoff and the dataset once the retry succeeds", async () => {
        vi.useFakeTimers();
        failNext = 1;
        const link = mountWithServer();
        await link.findComponent(RouterLinkStub).trigger("mouseenter");
        link.findComponent(POPOVER_STUB).vm.$emit("shown");
        await flushPromises();
        expect(datasetRequests).toBe(1);
        expect(historyRequests).toBe(0);
        expect(link.find(".dataset-details-popover").text()).toContain("Loading dataset details");

        await vi.advanceTimersByTimeAsync(RETRY_BACKOFF_CAP_MS);
        await flushPromises();
        expect(datasetRequests).toBe(2);
        expect(link.find(".dataset-details-popover").text()).not.toContain("Loading dataset details");
        expect(link.find("#dataset-details").exists()).toBe(true);
        // Nothing in the popover reads the dataset's history.
        expect(historyRequests).toBe(0);
    });

    it("does not retry a failed fetch after the popover is hidden", async () => {
        vi.useFakeTimers();
        failNext = 1;
        const link = mountWithServer();
        await link.findComponent(RouterLinkStub).trigger("mouseenter");
        const popover = link.findComponent(POPOVER_STUB);
        popover.vm.$emit("shown");
        await flushPromises();
        expect(datasetRequests).toBe(1);

        popover.vm.$emit("hidden");
        await vi.advanceTimersByTimeAsync(RETRY_BACKOFF_CAP_MS);
        await flushPromises();
        expect(datasetRequests).toBe(1);
    });
});
