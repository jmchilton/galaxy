import { getLocalVue, nth } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SampleSheetColumnDefinitions } from "@/api";
import type { Step } from "@/stores/workflowStepStore";
import { ensureDefined } from "@/utils/assertions";

import FormCollectionType from "./FormCollectionType.vue";
import FormColumnDefinitions from "./FormColumnDefinitions.vue";
import FormInputCollection from "./FormInputCollection.vue";
import FormElement from "@/components/Form/FormElement.vue";

const localVue = getLocalVue();

const CONDITION_COLUMN: SampleSheetColumnDefinitions = [
    { name: "Condition", type: "string", description: "", optional: false },
];

function stepWithCollectionType(collectionType: string | null) {
    const step: Pick<Step, "id" | "type" | "tool_state"> = {
        id: 3,
        type: "data_collection_input",
        tool_state: {
            collection_type: JSON.stringify(collectionType),
            optional: "false",
            tag: "null",
            format: "null",
            fields: "null",
            column_definitions: "null",
        },
    };
    // Original fixture omits input_connections, inputs, name and outputs;
    // this form only consumes the fields checked above.
    return step as unknown as Step;
}

function lastEmittedState(wrapper: VueWrapper) {
    return nth(wrapper.emitted<[Record<string, unknown>]>("onChange"), -1)[0];
}

function mountCollectionForm() {
    return shallowMount(FormInputCollection, {
        props: {
            step: stepWithCollectionType("list"),
            datatypes: [],
        },
        global: localVue,
    });
}

afterEach(() => {
    if (vi.isFakeTimers()) {
        vi.clearAllTimers();
    }
    vi.useRealTimers();
});
enableAutoUnmount(afterEach);

describe("FormInputCollection", () => {
    it("shows the values stored on the step", () => {
        const wrapper = mountCollectionForm();
        expect(wrapper.getComponent(FormCollectionType).props("value")).toBe("list");
    });

    it("sends a later edit together with an earlier one the step has not echoed yet", async () => {
        const wrapper = mountCollectionForm();
        vi.useFakeTimers();
        wrapper.getComponent(FormCollectionType).vm.$emit("onChange", "sample_sheet:paired");
        await wrapper.vm.$nextTick();
        expect(wrapper.findComponent(FormColumnDefinitions).exists()).toBe(true);

        wrapper.getComponent(FormColumnDefinitions).vm.$emit("onChange", CONDITION_COLUMN);
        vi.advanceTimersByTime(500);
        await wrapper.vm.$nextTick();

        const state = lastEmittedState(wrapper);
        expect(state.collection_type).toBe("sample_sheet:paired");
        expect(state.column_definitions).toEqual(CONDITION_COLUMN);
    });

    it("keeps the edited value when the step echoes an older one", async () => {
        const wrapper = mountCollectionForm();
        wrapper.getComponent(FormCollectionType).vm.$emit("onChange", "sample_sheet");
        wrapper.getComponent(FormCollectionType).vm.$emit("onChange", "sample_sheet:paired");
        await wrapper.setProps({ step: stepWithCollectionType("sample_sheet") });

        expect(wrapper.getComponent(FormCollectionType).props("value")).toBe("sample_sheet:paired");
        const optionalField = wrapper.findAllComponents(FormElement).find((field) => field.props("id") === "optional");
        expect(optionalField).toBeDefined();
        const emittedCount = ensureDefined(wrapper.emitted("onChange")).length;
        ensureDefined(optionalField).vm.$emit("input", true);
        expect(wrapper.emitted("onChange")).toHaveLength(emittedCount + 1);
        expect(lastEmittedState(wrapper)).toMatchObject({
            collection_type: "sample_sheet:paired",
            optional: true,
        });
    });
});
