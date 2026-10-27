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

    it("offers Compare outputs to registered users only", async () => {
        const registered = await mountWith(getFakeRegisteredUser());
        expect(registered.find(".stored-workflow-compare-outputs").exists()).toBe(true);
        const anonymous = await mountWith({ isAnonymous: true, total_disk_usage: 0, nice_total_disk_usage: "0 bytes" });
        expect(anonymous.find(".breadcrumb-heading").text()).toContain("Two cats");
        expect(anonymous.find(".stored-workflow-compare-outputs").exists()).toBe(false);
    });
});
