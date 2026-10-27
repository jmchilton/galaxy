import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";

import StoredWorkflowInvocations from "./StoredWorkflowInvocations.vue";

const { server, http } = useServerMock();

describe("StoredWorkflowInvocations", () => {
    it("links Compare outputs to the workflow's output comparison", async () => {
        server.use(
            http.get("/api/workflows/{workflow_id}", ({ response }) => {
                return response(200).json({ id: "wf1", name: "Two cats" } as never);
            }),
        );
        const localVue = getLocalVue();
        const wrapper = mount(StoredWorkflowInvocations as object, {
            props: { storedWorkflowId: "wf1" },
            global: { ...localVue, stubs: { ...localVue.stubs, GridInvocation: true } },
        });
        await flushPromises();

        const link = wrapper.find("a.stored-workflow-compare-outputs");
        expect(link.text()).toContain("Compare outputs");
        expect(link.attributes("href")).toBe("/comparisons?kind=output_runs&workflow_id=wf1");
        expect(wrapper.find(".breadcrumb-heading").text()).toContain("Two cats");
    });
});
