import { createTestingPinia } from "@pinia/testing";
import { getFakeRegisteredUser } from "@tests/test-data";
import { deferred } from "@tests/vitest/deferred";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RegisteredUser } from "@/api";
import { useServerMock } from "@/api/client/__mocks__";
import type { JobBaseModel, JobState as JobStateType, ShowFullJobResponse } from "@/api/jobs";
import { useUserStore } from "@/stores/userStore";

import JobState from "./JobState.vue";

vi.mock("vue-router", () => ({
    useRoute: vi.fn(() => ({})),
}));

enableAutoUnmount(afterEach);

const localVue = getLocalVue();
const { server, http } = useServerMock();

const FAKE_USER = getFakeRegisteredUser({ id: "user-123" });

const BASE_JOB: JobBaseModel = {
    model_class: "Job",
    id: "job-abc",
    state: "running",
    tool_id: "some_tool",
    create_time: "2024-01-01T00:00:00",
    update_time: "2024-01-01T00:01:00",
};

const FULL_JOB = {
    ...BASE_JOB,
    inputs: {},
    outputs: {},
    output_collections: {},
    params: {},
    user_id: "user-123",
} satisfies ShowFullJobResponse;

const SELECTORS = {
    STOP_BTN: ".stop-job-btn",
    STATE_BADGE: ".job-state-badge",
};

function mountJobState(job: JobBaseModel | ShowFullJobResponse, user: RegisteredUser | null = FAKE_USER) {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
    const userStore = useUserStore(pinia);
    userStore.currentUser = user;
    return mount(JobState, {
        props: { job },
        global: withPlugins(localVue, pinia),
    });
}

describe("JobState.vue", () => {
    beforeEach(() => {
        server.use(
            http.delete("/api/jobs/{job_id}", ({ response }) => {
                return response(200).json(true);
            }),
        );
    });

    it("renders the job state badge with the job state text", async () => {
        const wrapper = mountJobState(BASE_JOB);
        await flushPromises();
        expect(wrapper.get(SELECTORS.STATE_BADGE).text()).toContain("running");
    });

    it("shows the stop button for a non-terminal state when using JobBaseModel (no user_id)", async () => {
        const wrapper = mountJobState({ ...BASE_JOB, state: "running" });
        await flushPromises();
        expect(wrapper.find(SELECTORS.STOP_BTN).exists()).toBe(true);
    });

    it.each(["ok", "error", "deleted", "failed"] satisfies JobStateType[])(
        "hides the stop button for the terminal state %s",
        async (state) => {
            const wrapper = mountJobState({ ...BASE_JOB, state });
            await flushPromises();
            expect(wrapper.find(SELECTORS.STOP_BTN).exists()).toBe(false);
        },
    );

    it("shows the stop button when ShowFullJobResponse user_id matches current user", async () => {
        const wrapper = mountJobState({ ...FULL_JOB, state: "running", user_id: FAKE_USER.id });
        await flushPromises();
        expect(wrapper.find(SELECTORS.STOP_BTN).exists()).toBe(true);
    });

    it("hides the stop button when ShowFullJobResponse user_id does not match current user", async () => {
        const wrapper = mountJobState({ ...FULL_JOB, state: "running", user_id: "someone-else" });
        await flushPromises();
        expect(wrapper.find(SELECTORS.STOP_BTN).exists()).toBe(false);
    });

    it("hides the stop button when no user is logged in", async () => {
        const wrapper = mountJobState(BASE_JOB, null);
        await flushPromises();
        expect(wrapper.find(SELECTORS.STOP_BTN).exists()).toBe(false);
    });

    it("calls DELETE /api/jobs/{job_id} when stop button is clicked", async () => {
        let deletedJobId: string | undefined;
        server.use(
            http.delete("/api/jobs/{job_id}", ({ response, params }) => {
                deletedJobId = params.job_id;
                return response(200).json(true);
            }),
        );

        const wrapper = mountJobState({ ...BASE_JOB, state: "running" });
        await flushPromises();

        await wrapper.get(SELECTORS.STOP_BTN).trigger("click");
        await flushPromises();

        expect(deletedJobId).toBe(BASE_JOB.id);
    });

    it("disables the stop button while stopping is in progress", async () => {
        const deleteCompletion = deferred<void>();
        server.use(
            http.delete("/api/jobs/{job_id}", async ({ response }) => {
                await deleteCompletion.promise;
                return response(200).json(true);
            }),
        );

        const wrapper = mountJobState({ ...BASE_JOB, state: "running" });
        await flushPromises();

        const stopButton = wrapper.get(SELECTORS.STOP_BTN);
        await stopButton.trigger("click");
        await flushPromises();

        try {
            expect(stopButton.classes()).toContain("g-disabled");
        } finally {
            deleteCompletion.resolve();
            await flushPromises();
        }

        expect(stopButton.classes()).not.toContain("g-disabled");
    });
});
