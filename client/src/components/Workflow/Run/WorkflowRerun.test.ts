import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount, type Wrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia } from "pinia";
import { afterEach, describe, expect, it, vi } from "vitest";
import type Vue from "vue";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import WorkflowRerun from "./WorkflowRerun.vue";
import WorkflowRun from "./WorkflowRun.vue";
import GAlert from "@/components/BaseComponents/GAlert.vue";

const localVue = getLocalVue();
const { server, http } = useServerMock();

describe("WorkflowRerun", () => {
    let wrapper: Wrapper<Vue> | undefined;

    afterEach(() => {
        wrapper?.destroy();
        wrapper = undefined;
        vi.useRealTimers();
        vi.restoreAllMocks();
    });

    it("shows loading while a failed rerun request waits to retry", async () => {
        vi.useFakeTimers();
        server.use(
            http.get("/api/invocations/{invocation_id}/request", ({ response }) =>
                response("5XX").json({ err_msg: "unavailable", err_code: 0 }, { status: 503 }),
            ),
        );
        wrapper = shallowMount(WorkflowRerun as object, {
            propsData: { invocationId: "invocation-id" },
            localVue,
            pinia: createPinia(),
        });
        await flushPromises();
        expect(wrapper.find("loadingspan-stub").attributes("message")).toBe("Loading workflow rerun data");
        expect(wrapper.findComponent(GAlert).exists()).toBe(false);
        expect(wrapper.findComponent(WorkflowRun).exists()).toBe(false);
    });

    it("renders the run form after failing to switch to the original history", async () => {
        vi.spyOn(console, "error").mockImplementation(() => {});
        server.use(
            http.get("/api/invocations/{invocation_id}/request", ({ response }) =>
                response.untyped(
                    HttpResponse.json({ history_id: "history-id", workflow_id: "workflow-id", instance: true }),
                ),
            ),
            http.untyped.get("/history/set_as_current", () =>
                HttpResponse.json({ err_msg: "unavailable", err_code: 0 }, { status: 500 }),
            ),
        );
        wrapper = shallowMount(WorkflowRerun as object, {
            propsData: { invocationId: "invocation-id" },
            localVue,
            pinia: createPinia(),
        });
        await flushPromises();
        expect(wrapper.find("loadingspan-stub").exists()).toBe(false);
        expect(wrapper.findComponent(WorkflowRun).exists()).toBe(true);
    });
});
