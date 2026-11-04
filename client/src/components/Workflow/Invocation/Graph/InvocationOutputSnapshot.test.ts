import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import { expect, it } from "vitest";

import type { GraphStep } from "@/composables/useInvocationGraph";

import InvocationOutputPreview from "./InvocationOutputPreview.vue";
import InvocationOutputSnapshot from "./InvocationOutputSnapshot.vue";

const STEP = { id: 4, state: "ok" } as unknown as GraphStep;

it("previews the item under its step's state, summarizing collections rather than loading every element", () => {
    const wrapper = shallowMount(InvocationOutputSnapshot as object, {
        propsData: { item: { src: "hdca", id: "c1" }, step: STEP },
        localVue: getLocalVue(),
    });
    expect(wrapper.findComponent(InvocationOutputPreview).props()).toMatchObject({
        item: { src: "hdca", id: "c1" },
        step: STEP,
        summarizeCollection: true,
    });
});
