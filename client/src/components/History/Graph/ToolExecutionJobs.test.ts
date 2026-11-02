import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import ToolExecutionJobs from "./ToolExecutionJobs.vue";

const mockJobs = ref<{ id: string }[]>([]);

vi.mock("./useToolExecutionJobs", () => ({
    useToolExecutionJobs: () => ({ jobs: mockJobs, loading: ref(false), error: ref(null) }),
}));

const JobHeaderStub = {
    name: "JobHeader",
    props: ["jobId"],
    template: "<div><slot name='pagination' /></div>",
};

const PAGE_SELECTOR = "nav[aria-label='Jobs'] button[data-page]";
const CURRENT_SELECTOR = "nav[aria-label='Jobs'] button[aria-current='page']";

function mountJobs(ids: string[]) {
    mockJobs.value = ids.map((id) => ({ id }));
    return mount(ToolExecutionJobs as object, {
        localVue: getLocalVue(),
        propsData: { toolExecutionId: "execution_id" },
        stubs: {
            GTabs: { template: "<div><slot name='nav-end' /><slot /></div>" },
            JobHeader: JobHeaderStub,
            JobDetailsTabs: true,
        },
    });
}

describe("ToolExecutionJobs", () => {
    it("shows no job pager for a single job", () => {
        const wrapper = mountJobs(["job_1"]);
        expect(wrapper.findAll(PAGE_SELECTOR).length).toBe(0);
    });

    it("switches the viewed job from the job pager", async () => {
        const wrapper = mountJobs(["job_1", "job_2"]);
        expect(wrapper.findAll(PAGE_SELECTOR).map((page) => page.text())).toEqual(["1", "2"]);
        expect(wrapper.findComponent(JobHeaderStub).props("jobId")).toBe("job_1");

        await wrapper
            .findAll(PAGE_SELECTOR)
            .find((page) => page.text() === "2")!
            .trigger("click");

        expect(wrapper.find(CURRENT_SELECTOR).text()).toBe("2");
        expect(wrapper.findComponent(JobHeaderStub).props("jobId")).toBe("job_2");
    });
});
