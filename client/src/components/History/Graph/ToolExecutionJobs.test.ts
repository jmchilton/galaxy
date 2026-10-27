import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import ToolExecutionJobs from "./ToolExecutionJobs.vue";

const { server, http } = useServerMock();

const TABS_STUB = { name: "JobDetailsTabs", props: ["jobId", "infoTitle", "infoIcon"], template: "<div />" };
const HEADER_STUB = { name: "JobHeader", props: ["jobId"], template: "<div><slot name='pagination' /></div>" };

function toolRequest(jobIds: string[]) {
    return {
        id: "tr1",
        request: {},
        state: "submitted",
        implicit_collections: [],
        jobs: jobIds.map((id) => ({ src: "job", id })),
    };
}

let failRequest: boolean;
let jobIds: string[];
let batchRequests: URLSearchParams[];
// While set, the first batch's response waits for it.
let firstBatchGate: Promise<void> | undefined;

beforeEach(() => {
    failRequest = false;
    jobIds = ["j1", "j2", "j3"];
    batchRequests = [];
    firstBatchGate = undefined;
    server.use(
        http.untyped.get("/api/jobs", async ({ request }) => {
            const query = new URL(request.url).searchParams;
            batchRequests.push(query);
            if (query.get("implicit_collection_jobs_id") === "icj1") {
                await firstBatchGate;
            } else if (query.get("implicit_collection_jobs_id") === "icj-other") {
                return HttpResponse.json([{ id: "k1", model_class: "Job", state: "ok" }]);
            }
            if (failRequest) {
                return HttpResponse.json({ err_msg: "nope", err_code: 500 }, { status: 500 });
            }
            // newest first, as the index sorts
            return HttpResponse.json([...jobIds].reverse().map((id) => ({ id, model_class: "Job", state: "ok" })));
        }),
        http.untyped.get("/api/tool_requests/:id", () =>
            failRequest
                ? HttpResponse.json({ err_msg: "nope", err_code: 500 }, { status: 500 })
                : HttpResponse.json(toolRequest(jobIds)),
        ),
    );
});

async function mountJobs(props: Record<string, unknown> = {}) {
    const localVue = getLocalVue();
    const wrapper = mount(ToolExecutionJobs as object, {
        props: { toolExecutionId: "tr1", ...props },
        global: { ...localVue, stubs: { ...localVue.stubs, JobDetailsTabs: TABS_STUB, JobHeader: HEADER_STUB } },
    });
    await flushPromises();
    return wrapper;
}

describe("ToolExecutionJobs", () => {
    it("shows the first job of a tool execution and pages through the others", async () => {
        const wrapper = await mountJobs({ infoTitle: "Step" });
        const tabs = wrapper.findComponent(TABS_STUB);
        expect(tabs.props("jobId")).toBe("j1");
        expect(tabs.props("infoTitle")).toBe("Step");
        await wrapper.find("button[aria-label='Go to page 3']").trigger("click");
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("j3");
        expect(wrapper.findComponent(HEADER_STUB).props("jobId")).toBe("j3");
    });

    it("shows no pager for a single job", async () => {
        jobIds = ["j1"];
        const wrapper = await mountJobs();
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("j1");
        expect(wrapper.find("button[aria-label='Go to page 2']").exists()).toBe(false);
    });

    it("explains a tool execution without jobs", async () => {
        jobIds = [];
        const wrapper = await mountJobs();
        expect(wrapper.text()).toContain("No job associated with this tool execution.");
        expect(wrapper.findComponent(TABS_STUB).exists()).toBe(false);
    });

    it("explains a failed load", async () => {
        failRequest = true;
        const wrapper = await mountJobs();
        expect(wrapper.text()).toContain("Failed to load tool execution details.");
    });

    it("pages through a mapped batch's jobs, oldest first", async () => {
        const wrapper = await mountJobs({ toolExecutionId: undefined, implicitCollectionJobsId: "icj1" });
        expect(batchRequests).toHaveLength(1);
        expect(batchRequests[0]!.get("implicit_collection_jobs_id")).toBe("icj1");
        expect(batchRequests[0]!.get("order_by")).toBe("create_time");
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("j1");
        await wrapper.find("button[aria-label='Go to page 2']").trigger("click");
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("j2");
    });

    it("opens a batch on the given job", async () => {
        const wrapper = await mountJobs({
            toolExecutionId: undefined,
            implicitCollectionJobsId: "icj1",
            initialJobId: "j2",
        });
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("j2");
    });

    it("keeps the newer batch's jobs when an older response lands late", async () => {
        let release: () => void = () => {};
        firstBatchGate = new Promise((resolve) => (release = resolve));
        const wrapper = await mountJobs({ toolExecutionId: undefined, implicitCollectionJobsId: "icj1" });
        await wrapper.setProps({ implicitCollectionJobsId: "icj-other" } as object);
        await flushPromises();
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("k1");
        release();
        await flushPromises();
        expect(wrapper.findComponent(TABS_STUB).props("jobId")).toBe("k1");
    });

    it("explains an empty batch and a failed batch load", async () => {
        jobIds = [];
        const empty = await mountJobs({ toolExecutionId: undefined, implicitCollectionJobsId: "icj1" });
        expect(empty.text()).toContain("This batch has no jobs.");
        failRequest = true;
        const failed = await mountJobs({ toolExecutionId: undefined, implicitCollectionJobsId: "icj2" });
        expect(failed.text()).toContain("Failed to load the batch's jobs.");
    });
});
