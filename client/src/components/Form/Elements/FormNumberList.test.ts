import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount, type VueWrapper } from "@vue/test-utils";
import { afterEach, describe, expect, it } from "vitest";

import FormNumber from "./FormNumber.vue";
import FormNumberList from "./FormNumberList.vue";

const localVue = getLocalVue();

enableAutoUnmount(afterEach);

const SELECTORS = {
    INPUT: "input.ui-input",
    ADD: "[data-description='add value']",
    REMOVE: "[data-description='remove value']",
};

function mountFormNumberList(value: number[] | null) {
    return mount(FormNumberList, {
        props: { value, type: "integer" },
        global: localVue,
    });
}

function inputValues(wrapper: VueWrapper) {
    return wrapper.findAll(SELECTORS.INPUT).map((input) => (input.element as HTMLInputElement).value);
}

function lastEmittedValue(wrapper: VueWrapper) {
    return wrapper.emitted("input")!.at(-1);
}

describe("FormNumberList", () => {
    it("renders a number field per value", () => {
        const wrapper = mountFormNumberList([1, 2]);

        expect(inputValues(wrapper)).toEqual(["1", "2"]);
    });

    it("starts with one empty field that cannot be removed", () => {
        const wrapper = mountFormNumberList(null);

        expect(wrapper.findAllComponents(FormNumber)).toHaveLength(1);
        expect(inputValues(wrapper)).toEqual([""]);
        expect(wrapper.find(SELECTORS.REMOVE).classes()).toContain("g-disabled");
    });

    it("emits the entered values as numbers", async () => {
        const wrapper = mountFormNumberList([1]);

        await wrapper.find(SELECTORS.ADD).trigger("click");
        await wrapper.findAll(SELECTORS.INPUT).at(1)!.setValue("3");

        expect(lastEmittedValue(wrapper)).toEqual([[1, 3]]);
    });

    it("removes a value", async () => {
        const wrapper = mountFormNumberList([1, 2]);

        await wrapper.findAll(SELECTORS.REMOVE).at(0)!.trigger("click");

        expect(lastEmittedValue(wrapper)).toEqual([[2]]);
        expect(wrapper.findAllComponents(FormNumber)).toHaveLength(1);
        expect(inputValues(wrapper)).toEqual(["2"]);
    });

    it("emits null once every field is empty", async () => {
        const wrapper = mountFormNumberList([1]);

        await wrapper.find(SELECTORS.INPUT).setValue("");

        expect(lastEmittedValue(wrapper)).toEqual([null]);
    });
});
