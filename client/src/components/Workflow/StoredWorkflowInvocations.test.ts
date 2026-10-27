import { createTestingPinia } from "@pinia/testing";
import { getFakeRegisteredUser } from "@tests/test-data";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnyUser } from "@/api";
import { useServerMock } from "@/api/client/__mocks__";

import StoredWorkflowInvocations from "./StoredWorkflowInvocations.vue";

const { server, http } = useServerMock();

async function mountWith(currentUser: AnyUser) {
    const localVue = getLocalVue();
    const pinia = createTestingPinia({ createSpy: vi.fn, initialState: { userStore: { currentUser } } });
    const wrapper = mount(StoredWorkflowInvocations as object, {
        props: { storedWorkflowId: "wf1" },
        global: {
            ...localVue,
            plugins: [...(localVue.plugins ?? []), pinia],
            stubs: { ...localVue.stubs, GridInvocation: true },
        },
    });
    await flushPromises();
    return wrapper;
}

describe("StoredWorkflowInvocations", () => {
    beforeEach(() => {
        server.use(
            http.get("/api/workflows/{workflow_id}", ({ response }) => {
                return response(200).json({ id: "wf1", name: "Two cats" } as never);
            }),
        );
    });

    it("hides Compare outputs from anonymous users, who have no runs to compare", async () => {
        const wrapper = await mountWith({ isAnonymous: true, total_disk_usage: 0, nice_total_disk_usage: "0 bytes" });
        expect(wrapper.find(".breadcrumb-heading").text()).toContain("Two cats");
        expect(wrapper.find(".stored-workflow-compare-outputs").exists()).toBe(false);
    });

    it("links Compare outputs to the workflow's output comparison", async () => {
        const wrapper = await mountWith(getFakeRegisteredUser());

        const link = wrapper.find("a.stored-workflow-compare-outputs");
        expect(link.text()).toContain("Compare outputs");
        expect(link.attributes("href")).toBe("/comparisons?kind=output_runs&workflow_id=wf1");
        expect(wrapper.find(".breadcrumb-heading").text()).toContain("Two cats");
    });
});
