import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import type { GraphStep, GraphStepState, InvocationOutputItem } from "@/composables/useInvocationGraph";

import InvocationOutputPreview from "./InvocationOutputPreview.vue";

const { server, http } = useServerMock();

/** Counts of requests for each dataset's details and content, and for each collection */
let requests: Record<string, number>;
/** Shared by a test's mounts, so they share stores like previews on one page */
let localVue: ReturnType<typeof getLocalVue>;

function count(key: string) {
    requests[key] = (requests[key] ?? 0) + 1;
}

beforeEach(() => {
    localVue = getLocalVue();
    requests = {};
    server.use(
        http.get("/api/datasets/{dataset_id}", ({ params, response }) => {
            count(`details ${params.dataset_id}`);
            return response.untyped(HttpResponse.json({ id: params.dataset_id, extension: "txt", peek: "" }));
        }),
        http.get("/api/datasets/{dataset_id}/get_content_as_text", ({ params, response }) => {
            count(`content ${params.dataset_id}`);
            return response.untyped(HttpResponse.json({ item_data: "text", truncated: false }));
        }),
        http.get("/api/dataset_collections/{hdca_id}", ({ params, response }) => {
            count(`collection ${params.hdca_id}`);
            return response.untyped(HttpResponse.json({ id: params.hdca_id, name: "lines", elements: [] }));
        }),
    );
});

/** The producing step, with only what the preview reads */
function producedBy(state: GraphStepState, type: GraphStep["type"] = "tool") {
    return { type, state } as GraphStep;
}

/** Mount a preview. The dataset display is stubbed, so the requests counted for a dataset are only the preview's
 * own reloads; the collection display is real, and loads its collection when it mounts. */
async function mountPreview(item: InvocationOutputItem, stepState: GraphStepState, stepType?: GraphStep["type"]) {
    const wrapper = shallowMount(InvocationOutputPreview, {
        propsData: { item, step: producedBy(stepState, stepType) },
        localVue,
        stubs: { CollectionDisplay: false },
    });
    await flushPromises();
    return wrapper;
}

describe("InvocationOutputPreview", () => {
    it("shows that the output isn't ready while its step runs, without loading it", async () => {
        const wrapper = await mountPreview({ src: "hdca", id: "c0" }, "running");
        expect(wrapper.text()).toBe("This output isn't ready yet: the step is running.");
        expect(requests).toEqual({});
    });

    // a subworkflow step's graph state comes from its invocation step, which stays scheduled (shown as queued)
    it("shows a subworkflow's output although the subworkflow step reads as queued", async () => {
        await mountPreview({ src: "hdca", id: "c9" }, "queued", "subworkflow");
        expect(requests).toEqual({ "collection c9": 1 });
    });

    it("reloads a dataset when its producing step changes state", async () => {
        const wrapper = await mountPreview({ src: "hda", id: "d1" }, "setting_metadata");
        expect(requests).toEqual({});

        await wrapper.setProps({ step: producedBy("ok") });
        await flushPromises();
        expect(requests).toEqual({ "details d1": 1, "content d1": 1 });
    });

    it("reloads a dataset once its step is ready, not at each state its jobs pass through", async () => {
        const wrapper = await mountPreview({ src: "hda", id: "d4" }, "new");
        for (const state of ["queued", "running", "ok"] as const) {
            await wrapper.setProps({ step: producedBy(state) });
            await flushPromises();
        }
        expect(requests).toEqual({ "details d4": 1, "content d4": 1 });
    });

    // e.g. a failed step rerun with its outputs remapped keeps the same dataset ids
    it("reloads a dataset shown again after its step's state changed", async () => {
        const first = await mountPreview({ src: "hda", id: "d2" }, "error");
        first.unmount();

        await mountPreview({ src: "hda", id: "d2" }, "ok");
        expect(requests).toEqual({ "details d2": 1, "content d2": 1 });
    });

    it("keeps a dataset shown again under the same step state", async () => {
        const first = await mountPreview({ src: "hda", id: "d3" }, "ok");
        first.unmount();

        await mountPreview({ src: "hda", id: "d3" }, "ok");
        expect(requests).toEqual({});
    });

    it("reloads a collection when its producing step changes state", async () => {
        const wrapper = await mountPreview({ src: "hdca", id: "c1" }, "setting_metadata");
        expect(requests).toEqual({ "collection c1": 1 });

        await wrapper.setProps({ step: producedBy("ok") });
        await flushPromises();
        expect(requests).toEqual({ "collection c1": 2 });
    });
});
