import { composeStories } from "@storybook/vue3-vite";
import { emittedArg, getLocalVue } from "@tests/vitest/helpers";
import { useStoryMount } from "@tests/vitest/stories";
import { mount } from "@vue/test-utils";
import { describe, expect, it, onTestFinished } from "vitest";

import * as FormOptionalTextStories from "./FormOptionalText.stories";

import FormOptionalText from "./FormOptionalText.vue";

const stories = composeStories(FormOptionalTextStories);
const mountStory = useStoryMount();

const SELECTORS = {
    SWITCH: "input[type='checkbox']",
    TEXT_INPUT: "input[type='text']",
};

/** Mounts a story, whose harness passes every emitted `input` back as `value`, as a v-model parent does. */
function mountFormOptionalText(story) {
    return mountStory(story).getComponent(FormOptionalText);
}

describe("FormOptionalText", () => {
    it("switches on and shows an existing value", () => {
        const wrapper = mountFormOptionalText(stories.WithValue);

        expect(wrapper.find(SELECTORS.SWITCH).element.checked).toBe(true);
        expect(wrapper.find(SELECTORS.TEXT_INPUT).element.value).toBe(stories.WithValue.args.value);
    });

    it("emits null when switched off and an empty string when switched back on", async () => {
        const wrapper = mountFormOptionalText(stories.WithValue);
        const toggle = wrapper.find(SELECTORS.SWITCH);

        await toggle.setValue(false);
        expect(emittedArg(wrapper, "input", 0)).toBeNull();
        expect(wrapper.find(SELECTORS.TEXT_INPUT).exists()).toBe(false);

        await toggle.setValue(true);
        expect(emittedArg(wrapper, "input", 1)).toBe("");
        expect(wrapper.find(SELECTORS.TEXT_INPUT).element.value).toBe("");
    });

    it("starts switched off for a null value", () => {
        const wrapper = mountFormOptionalText(stories.Unset);

        expect(wrapper.find(SELECTORS.SWITCH).element.checked).toBe(false);
        expect(wrapper.find(SELECTORS.TEXT_INPUT).exists()).toBe(false);
    });

    it("switches on once its parent sets a value", async () => {
        // A plain mount, as a story can't change a live mount's props.
        const wrapper = mount(FormOptionalText, {
            global: getLocalVue(),
            props: stories.Unset.args,
        });
        onTestFinished(() => wrapper.unmount());
        const toggle = wrapper.find(SELECTORS.SWITCH);
        expect(toggle.element.checked).toBe(false);
        expect(wrapper.find(SELECTORS.TEXT_INPUT).exists()).toBe(false);

        await wrapper.setProps({ value: "" });

        expect(toggle.element.checked).toBe(true);
        expect(wrapper.find(SELECTORS.TEXT_INPUT).exists()).toBe(true);
    });
});
