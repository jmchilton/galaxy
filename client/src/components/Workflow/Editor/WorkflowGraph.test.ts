import { shallowMount } from "@vue/test-utils";
import type * as VueUse from "@vueuse/core";
import { createPinia, setActivePinia } from "pinia";
import { expect, it, vi } from "vitest";
import { nextTick, ref } from "vue";

import { DatatypesMapperModel } from "@/components/Datatypes/model";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { type Step, useWorkflowStepStore } from "@/stores/workflowStepStore";

import WorkflowGraph from "./WorkflowGraph.vue";

vi.mock("@vueuse/core", async (importOriginal) => ({
    ...(await importOriginal<typeof VueUse>()),
    useElementBounding: () => ({
        width: ref(0),
        height: ref(0),
        x: ref(0),
        y: ref(0),
        top: ref(0),
        left: ref(0),
        right: ref(0),
        bottom: ref(0),
        update: vi.fn(),
    }),
}));

it("waits for measured viewport and node dimensions before centering an already selected step", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const state = useWorkflowStateStore("invocation-test");
    const stepStore = useWorkflowStepStore("invocation-test");
    const step = { id: 4, type: "tool", position: { left: 1000, top: 700 } } as Step;
    stepStore.steps = { 4: step };
    state.stepPosition[4] = { width: 0, height: 0 } as (typeof state.stepPosition)[number];
    const wrapper = shallowMount(WorkflowGraph, {
        props: {
            steps: stepStore.steps,
            scrollToId: 4,
            readonly: true,
            showMinimap: false,
            showZoomControls: false,
            datatypesMapper: new DatatypesMapperModel({
                datatypes: [],
                datatypes_mapping: { ext_to_class_name: {}, class_to_classes: {} },
            }),
        },
        global: { plugins: [pinia], provide: { workflowId: "invocation-test" } },
    });
    await nextTick();
    expect(wrapper.emitted("scrollTo")).toBeUndefined();
    state.stepPosition[4] = { width: 200, height: 100 } as (typeof state.stepPosition)[number];
    await nextTick();
    expect(wrapper.emitted("scrollTo")).toBeUndefined();
    const viewport = wrapper.findComponent({ name: "AdaptiveGrid" }).props("viewportBounds");
    viewport.width.value = 800;
    await nextTick();
    expect(wrapper.emitted("scrollTo")).toBeUndefined();
    viewport.height.value = 600;
    await nextTick();
    await nextTick();
    expect(wrapper.emitted("scrollTo")).toHaveLength(1);
    expect(state.position).toEqual([-700, -450]);
    expect(wrapper.find(".node-area").attributes("style")).toContain("translate(-700px, -450px) scale(1)");
    wrapper.unmount();
});
