import { currentPagerPage, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";

import { useServerMock } from "@/api/client/__mocks__";

import ToolExecutionJobs from "./ToolExecutionJobs.vue";

const { server, http } = useServerMock();

const SELECTORS = {
    JOB_HEADER: ".job-header-stub",
};

// Renders only the pager slot and the shown job id, so the spec needs no job API mocks
const JobHeaderStub = defineComponent({
    props: { jobId: { type: String, required: true } },
    setup(props, { slots }) {
        return () => h("div", { class: "job-header-stub", "data-job-id": props.jobId }, slots.pagination?.());
    },
});

function mockJobs(jobIds: string[]) {
    server.use(
        http.get("/api/tool_requests/{id}", ({ response, params }) =>
            response(200).json({
                id: params.id,
                implicit_collections: [],
                jobs: jobIds.map((id) => ({ id, src: "job" as const })),
                request: {},
            }),
        ),
    );
}

async function mountToolExecutionJobs() {
    const localVue = getLocalVue();
    const wrapper = mount(ToolExecutionJobs as object, {
        props: { toolExecutionId: "tool-request-1" },
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, JobHeader: JobHeaderStub, JobDetailsTabs: true },
        },
    });
    await flushPromises();
    return wrapper;
}

describe("ToolExecutionJobs", () => {
    it("pages through the jobs of the execution", async () => {
        mockJobs(["job-1", "job-2", "job-3"]);
        const wrapper = await mountToolExecutionJobs();

        expect(wrapper.find(SELECTORS.JOB_HEADER).attributes("data-job-id")).toBe("job-1");
        expect(currentPagerPage(wrapper)).toBe("1");

        await goToPage(wrapper, 3);

        expect(currentPagerPage(wrapper)).toBe("3");
        expect(wrapper.find(SELECTORS.JOB_HEADER).attributes("data-job-id")).toBe("job-3");
    });

    it("shows no pager for a single job", async () => {
        mockJobs(["job-1"]);
        const wrapper = await mountToolExecutionJobs();

        expect(wrapper.find(SELECTORS.JOB_HEADER).attributes("data-job-id")).toBe("job-1");
        expect(pagerPages(wrapper)).toEqual([]);
    });
});
