import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { RunStep } from "./stepParameterTree";

import WorkflowRunStepParameters from "./WorkflowRunStepParameters.vue";

async function stub(name: string, props: string[], emits: string[]) {
    const { defineComponent, h } = await import("vue");
    return { default: defineComponent({ name, props, emits, render: () => h("div") }) };
}

vi.mock("@/components/Form/FormDisplay.vue", () => stub("FormDisplay", ["inputs"], ["onChange"]));
vi.mock("./StepParameterPicker.vue", () =>
    stub(
        "StepParameterPicker",
        ["show", "view", "tree", "selectedKeys", "workflowId", "version"],
        ["apply", "update:show", "update:view"],
    ),
);

const FormDisplayStub = { name: "FormDisplay" };
const StepParameterPickerStub = { name: "StepParameterPicker" };

const globalConfig = getLocalVue();

const steps: RunStep[] = [
    { step_index: 0, step_type: "data_input", inputs: [] },
    {
        step_index: 1,
        step_type: "tool",
        step_name: "Echo",
        inputs: [
            { name: "threshold", type: "float", label: "Threshold", value: "0.5" },
            {
                name: "queries",
                type: "repeat",
                title: "Query",
                cache: [
                    [{ name: "column", type: "text", value: "c1" }],
                    [{ name: "column", type: "text", value: "c2" }],
                ],
            },
            { name: "column", type: "data_column", data_ref: "input1", label: "Column", value: "1" },
            { name: "input1", type: "data", value: null },
        ],
    },
];

function mountParameters(props: Record<string, unknown> = {}) {
    return mount(WorkflowRunStepParameters as object, {
        props: { steps, workflowId: "wf", version: 0, ...props },
        global: globalConfig,
    });
}

function lastOverrides(wrapper: ReturnType<typeof mountParameters>) {
    const emitted = wrapper.emitted("update:overrides") ?? [];
    return emitted[emitted.length - 1]?.[0];
}

function cards(wrapper: ReturnType<typeof mountParameters>) {
    return wrapper.findAll("[data-description='step parameter card']");
}

function cardForm(wrapper: ReturnType<typeof mountParameters>, key: string) {
    const card = wrapper.find(`[data-description='step parameter card'][data-parameter-key='${key}']`);
    return card.findComponent(FormDisplayStub);
}

function cardInput(wrapper: ReturnType<typeof mountParameters>, key: string) {
    return (cardForm(wrapper, key).props("inputs") as Record<string, unknown>[])[0]!;
}

describe("WorkflowRunStepParameters", () => {
    it("sends no overrides until a step parameter is chosen", () => {
        const wrapper = mountParameters();
        expect(cards(wrapper)).toHaveLength(0);
        expect(lastOverrides(wrapper)).toBeNull();
    });

    it("adds and removes cards from the picked set", async () => {
        const wrapper = mountParameters();
        const picker = wrapper.findComponent(StepParameterPickerStub);
        picker.vm.$emit("apply", ["1/threshold", "1/queries/1/column"]);
        await wrapper.vm.$nextTick();
        expect(cards(wrapper).map((card) => card.attributes("data-parameter-key"))).toEqual([
            "1/threshold",
            "1/queries/1/column",
        ]);
        expect(picker.props("selectedKeys")).toEqual(["1/threshold", "1/queries/1/column"]);
        // Unchanged, a card sends the workflow's saved value, typed as the tool form would.
        expect(lastOverrides(wrapper)).toEqual({ 1: { threshold: 0.5, queries: [{}, { column: "c2" }] } });

        picker.vm.$emit("apply", ["1/queries/1/column"]);
        await wrapper.vm.$nextTick();
        expect(cards(wrapper)).toHaveLength(1);
        expect(lastOverrides(wrapper)).toEqual({ 1: { queries: [{}, { column: "c2" }] } });

        await wrapper.find("[data-description='remove step parameter']").trigger("click");
        expect(cards(wrapper)).toHaveLength(0);
        expect(lastOverrides(wrapper)).toBeNull();
    });

    it("sends a card's changed value", async () => {
        const wrapper = mountParameters();
        wrapper.findComponent(StepParameterPickerStub).vm.$emit("apply", ["1/threshold"]);
        await wrapper.vm.$nextTick();
        const input = cardInput(wrapper, "1/threshold");
        expect(input).toMatchObject({ type: "float", label: "Threshold", value: "0.5" });
        cardForm(wrapper, "1/threshold").vm.$emit("onChange", { [input.name as string]: "0.9" });
        await wrapper.vm.$nextTick();
        expect(lastOverrides(wrapper)).toEqual({ 1: { threshold: 0.9 } });
    });

    it("keeps a card's changed value while other cards come and go", async () => {
        const wrapper = mountParameters();
        const picker = wrapper.findComponent(StepParameterPickerStub);
        picker.vm.$emit("apply", ["1/threshold"]);
        await wrapper.vm.$nextTick();
        const input = cardInput(wrapper, "1/threshold");
        cardForm(wrapper, "1/threshold").vm.$emit("onChange", { [input.name as string]: "0.9" });
        picker.vm.$emit("apply", ["1/threshold", "1/queries/0/column"]);
        await wrapper.vm.$nextTick();
        // The kept card's form isn't handed new inputs, which would reset it.
        expect(cardInput(wrapper, "1/threshold")).toBe(input);
        expect(lastOverrides(wrapper)).toEqual({ 1: { threshold: 0.9, queries: [{ column: "c1" }] } });
    });

    it("re-shows the overrides a rerun recorded, with their values", () => {
        const wrapper = mountParameters({
            isRerun: true,
            rerunOverrides: { 1: { threshold: 0.75 } },
        });
        expect(cardInput(wrapper, "1/threshold").value).toBe(0.75);
        expect(wrapper.find("[data-description='step parameter card']").text()).toContain("original run: 0.75");
        expect(lastOverrides(wrapper)).toEqual({ 1: { threshold: 0.75 } });
    });

    it("shows a link's parameters, presetting those it gives a value", () => {
        const wrapper = mountParameters({
            linkOverrides: JSON.stringify({ 1: { threshold: null, queries: [{ column: "x" }] } }),
        });
        expect(cards(wrapper)).toHaveLength(2);
        expect(cardInput(wrapper, "1/threshold").value).toBe("0.5");
        expect(cardInput(wrapper, "1/queries/0/column").value).toBe("x");
        expect(wrapper.find("[data-description='step parameter card']").text()).toContain("saved: 0.5");
    });

    it("lists link parameters it can't show, and link errors", () => {
        const dropped = mountParameters({
            linkOverrides: JSON.stringify({ 1: { column: "2", missing: 1 } }),
        });
        expect(cards(dropped)).toHaveLength(0);
        const items = dropped.findAll("[data-description='dropped step parameters'] li");
        expect(items.map((item) => item.attributes("data-parameter-key"))).toEqual(["1/column", "1/missing"]);
        expect(lastOverrides(dropped)).toBeNull();

        const invalid = mountParameters({ linkOverrides: "{" });
        expect(invalid.find("[data-description='step parameter link error']").text()).toContain("not valid JSON");
    });
});
