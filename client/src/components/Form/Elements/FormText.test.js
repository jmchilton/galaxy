import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { createPinia, disposePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished } from "vitest";

import FormText from "./FormText.vue";

const localVue = getLocalVue();

describe("FormText", () => {
    let pinia;
    beforeEach(() => {
        pinia = createPinia();
        const ownedPinia = pinia;
        onTestFinished(() => {
            disposePinia(ownedPinia);
            setActivePinia(undefined);
        });
    });
    enableAutoUnmount(afterEach);

    const mountFormText = (props) =>
        mount(FormText, {
            props,
            global: withPlugins(localVue, pinia),
        });

    it("renders text and password inputs with a text fallback", async () => {
        const wrapper = mountFormText({});
        const textInput = wrapper.find("input[type='text']");
        expect(textInput.exists()).toBe(true);
        await wrapper.setProps({ type: "password" });
        const passwordInput = wrapper.find("input[type='password']");
        expect(passwordInput.exists()).toBe(true);
        await wrapper.setProps({ type: "anyothertype" });
        const fallbackInput = wrapper.find("input[type='text']");
        expect(fallbackInput.exists()).toBe(true);
    });

    it("renders a textarea for area and multiple inputs", async () => {
        const wrapper = mountFormText({ area: true });
        const areaInput = wrapper.find("textarea");
        expect(areaInput.exists()).toBe(true);
        await wrapper.setProps({ area: false, multiple: true });
        const multipleInput = wrapper.find("textarea");
        expect(multipleInput.exists()).toBe(true);
    });

    it("renders and links a datalist with options", () => {
        const wrapper = mountFormText({ id: "text-input", datalist: ["one", "two", "three"] });
        expect(wrapper.find("datalist").exists()).toBe(true);
        expect(wrapper.find("option").exists()).toBe(true);
        expect(wrapper.find("[list='text-input-datalist']").exists()).toBe(true);
    });

    it("omits the datalist and its link without options", () => {
        for (const datalist of [undefined, []]) {
            const wrapper = mountFormText({ id: "section|text-input", datalist });
            expect(wrapper.find("datalist").exists()).toBe(false);
            expect(wrapper.find("[list]").exists()).toBe(false);
        }
    });

    it("applies text color, border color and custom class props", async () => {
        const wrapper = mountFormText({});
        const input = wrapper.get("input");
        expect(input.element.style.color).toBeFalsy();
        await wrapper.setProps({ color: "green" });
        expect(input.element.style.color).toBe("green");
        expect(input.element.style.borderColor).toBe("green");
        await wrapper.setProps({ cls: "my-custom-class" });
        expect(input.element.classList).toContain("my-custom-class");
    });

    it("renders a string value", () => {
        const value = "something";
        const wrapper = mountFormText({ value });
        const input = wrapper.get("input");
        expect(input.element.value).toEqual(value);
    });

    it("renders the first array value and joins multiple values with newlines", async () => {
        const value = ["field_1", "field_2", "field_3"];
        const wrapper = mountFormText({ value });
        const input = wrapper.get("input");
        expect(input.element.value).toEqual("field_1");
        await wrapper.setProps({ multiple: true });
        const textarea = wrapper.get("textarea");
        expect(textarea.element.value).toEqual("field_1\nfield_2\nfield_3");
    });

    it("renders an empty array as an empty string", () => {
        const value = [];
        const wrapper = mountFormText({ value });
        const input = wrapper.get("input");
        expect(input.element.value).toEqual("");
    });
});
