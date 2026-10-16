import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, suppressDebugConsole } from "@tests/vitest/helpers";
import { shallowMount, type VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import { invokeWorkflow } from "./services";

import WorkflowNavigationTitle from "../WorkflowNavigationTitle.vue";
import WorkflowRunFormSimple from "./WorkflowRunFormSimple.vue";
import FormDisplay from "@/components/Form/FormDisplay.vue";

vi.mock("@/composables/config");
vi.mock("./services", () => ({
    invokeWorkflow: vi.fn(),
    searchHistoryContents: vi.fn(),
}));
vi.mock("@/composables/useWorkflowInstance", () => ({
    useWorkflowInstance: () => ({ workflow: ref(null), loading: ref(false) }),
}));
vi.mock("@/composables/fileSources", () => ({
    useFileSources: () => ({ hasWritable: ref(false) }),
}));

const globalConfig = getLocalVue();

const HISTORY_ID = "hist1";

// ``input1 -> random_lines1`` with a ``${sample}`` rename on the tool step: the
// simple form only shows the data input and the workflow parameter.
function buildModel() {
    return {
        name: "Rerun Workflow",
        workflowId: "workflow1",
        historyId: HISTORY_ID,
        runData: { workflow_id: "stored1", version: 0 },
        wpInputs: { sample: { name: "sample", label: "sample", type: "text", optional: true } },
        steps: [
            {
                step_index: 0,
                step_label: "input1",
                step_type: "data_input",
                inputs: [{ name: "input", type: "data", optional: false }],
            },
            { step_index: 1, step_type: "tool", inputs: [] },
        ],
    };
}

function mountForm(rerunRequest?: Record<string, unknown>) {
    const pinia = createTestingPinia({
        createSpy: vi.fn,
        initialState: {
            userStore: { currentUser: { id: "user_id" } },
            historyStore: { storedHistories: { [HISTORY_ID]: { id: HISTORY_ID, name: "Current" } } },
        },
    });
    setActivePinia(pinia);
    return shallowMount(WorkflowRunFormSimple as object, {
        props: {
            model: buildModel(),
            canMutateCurrentHistory: true,
            isRerun: true,
            requestState: rerunRequest?.inputs,
            rerunRequest,
        },
        global: {
            ...globalConfig,
            plugins: [...(globalConfig.plugins ?? []), pinia],
        },
    });
}

function formInputValue(wrapper: VueWrapper, name: string) {
    return wrapper
        .findComponent(FormDisplay)
        .props("inputs")
        .find((input) => input.name === name)?.value;
}

async function submit(wrapper: VueWrapper) {
    wrapper.findComponent(WorkflowNavigationTitle).vm.$emit("on-execute");
    await flushPromises();
    expect(invokeWorkflow).toHaveBeenCalledTimes(1);
    return vi.mocked(invokeWorkflow).mock.calls[0]![1] as Record<string, unknown>;
}

const INPUTS = { input1: { src: "hda", id: "hda1" } };

describe("WorkflowRunFormSimple rerun prefill", () => {
    beforeEach(() => {
        suppressDebugConsole();
        vi.mocked(invokeWorkflow).mockReset();
        vi.mocked(invokeWorkflow).mockResolvedValue([{ id: "invocation_id" }]);
    });

    it("resubmits the original run's preferred object store", async () => {
        const request = await submit(mountForm({ inputs: INPUTS, preferred_object_store_id: "fast" }));
        expect(request.preferred_object_store_id).toBe("fast");
        expect(request).not.toHaveProperty("preferred_outputs_object_store_id");
        expect(request).not.toHaveProperty("preferred_intermediate_object_store_id");
    });

    it("resubmits the original run's split output and intermediate object stores", async () => {
        const request = await submit(
            mountForm({
                inputs: INPUTS,
                preferred_outputs_object_store_id: "archive",
                preferred_intermediate_object_store_id: "scratch",
            }),
        );
        expect(request.preferred_outputs_object_store_id).toBe("archive");
        expect(request.preferred_intermediate_object_store_id).toBe("scratch");
        expect(request).not.toHaveProperty("preferred_object_store_id");
    });

    it("resubmits a split run that only set an intermediate object store", async () => {
        const request = await submit(mountForm({ inputs: INPUTS, preferred_intermediate_object_store_id: "scratch" }));
        expect(request.preferred_intermediate_object_store_id).toBe("scratch");
        expect(request).not.toHaveProperty("preferred_outputs_object_store_id");
        expect(request).not.toHaveProperty("preferred_object_store_id");
    });

    it("leaves object stores and workflow parameters unset when the original run had none", async () => {
        const wrapper = mountForm({ inputs: INPUTS });
        expect(formInputValue(wrapper, "sample")).toBeUndefined();
        const request = await submit(wrapper);
        expect(request).not.toHaveProperty("preferred_object_store_id");
        expect(request).not.toHaveProperty("preferred_outputs_object_store_id");
        expect(request).not.toHaveProperty("preferred_intermediate_object_store_id");
        expect(request).toMatchObject({ history_id: HISTORY_ID, inputs_by: "step_index", batch: true });
        expect(request.replacement_params).toEqual({});
        expect(request).not.toHaveProperty("replacement_dict");
    });
});
