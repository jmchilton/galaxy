import { getLocalVue } from "@tests/vitest/helpers";
import { shallowMount } from "@vue/test-utils";
import { expect, it } from "vitest";

import type { GraphStep } from "@/composables/useInvocationGraph";

import type { EmbeddedOutput } from "./useEmbeddedOutputs";

import InvocationEmbeddedOutputs from "./InvocationEmbeddedOutputs.vue";
import InvocationOutputPreview from "./InvocationOutputPreview.vue";

const STEP = { id: 4, state: "running", position: { left: 100, top: 50 } } as unknown as GraphStep;

const OUTPUTS: EmbeddedOutput[] = [
    {
        key: "4-out_file1",
        label: "top_rows",
        item: { src: "hda", id: "d1" },
        step: STEP,
        rect: { x: 264, y: 50, width: 260, height: 170 },
        stepRect: { x: 100, y: 50, width: 144, height: 55 },
    },
];

function mountCards() {
    return shallowMount(InvocationEmbeddedOutputs as object, {
        propsData: { embedded: OUTPUTS },
        localVue: getLocalVue(),
    });
}

it("renders each embedded output as a card, previewing it under its step's state", () => {
    const cards = mountCards().findAll("[data-description='invocation embedded output']");
    expect(cards.length).toBe(1);
    expect(cards.at(0)!.text()).toContain("top_rows");
    const preview = cards.at(0)!.findComponent(InvocationOutputPreview);
    expect(preview.props("item")).toEqual({ src: "hda", id: "d1" });
    expect(preview.props("step")).toEqual(STEP);
});

it("summarizes collection outputs rather than previewing every element", () => {
    const preview = mountCards().findComponent(InvocationOutputPreview);
    expect(preview.props("summarizeCollection")).toBe(true);
});
