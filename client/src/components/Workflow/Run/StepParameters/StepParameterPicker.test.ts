import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { buildStepParameterTree, type RunStep } from "./stepParameterTree";

import StepParameterPicker from "./StepParameterPicker.vue";

const localVue = getLocalVue();

const STEPS: RunStep[] = [
    {
        step_index: 1,
        step_type: "tool",
        step_name: "echo",
        inputs: ["a", "b", "c"].map((name) => ({ name, type: "integer", label: name, value: 1 }) as any),
    },
];

const ROW = '[data-description="step parameter row"]';

function mountPicker(show: boolean, rowUpdates = { count: 0 }) {
    return mount(StepParameterPicker as any, {
        props: { show, tree: buildStepParameterTree({ steps: STEPS }), selectedKeys: [] },
        attachTo: document.body,
        global: {
            ...localVue,
            mixins: [
                {
                    updated(this: any) {
                        if (this.$?.type?.__name === "StepParameterTreeNode") {
                            rowUpdates.count++;
                        }
                    },
                },
            ],
        },
    });
}

describe("StepParameterPicker", () => {
    it("builds the tree's rows only while open", async () => {
        const wrapper = mountPicker(false);
        expect(wrapper.findAll(ROW)).toHaveLength(0);
        await wrapper.setProps({ show: true });
        expect(wrapper.findAll(ROW)).toHaveLength(3);
        wrapper.unmount();
    });

    it("re-renders only the toggled row", async () => {
        const rowUpdates = { count: 0 };
        const wrapper = mountPicker(true, rowUpdates);
        await wrapper.get(`[data-parameter-key="1/b"] input`).setValue(true);
        expect(rowUpdates.count).toBe(1);
        const apply = wrapper.findAll("button").find((button) => button.text().startsWith("Apply"));
        expect(apply?.text()).toBe("Apply (1)");
        await apply!.trigger("click");
        expect(wrapper.emitted("apply")).toEqual([[["1/b"]]]);
        wrapper.unmount();
    });
});
