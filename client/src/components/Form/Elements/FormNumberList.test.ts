import { composeStories } from "@storybook/vue3-vite";
import { type StoryOf, useStoryMount } from "@tests/vitest/stories";
import { describe, expect, it } from "vitest";

import * as FormNumberListStories from "./FormNumberList.stories";

import FormNumber from "./FormNumber.vue";
import FormNumberList from "./FormNumberList.vue";

const stories = composeStories(FormNumberListStories);
const mountStory = useStoryMount();

const SELECTORS = {
    INPUT: "input.ui-input",
    ADD: "[data-description='add value']",
    REMOVE: "[data-description='remove value']",
};

/** Mounts a story, whose harness passes every emitted `input` back as `value`, as the form does. */
function mountFormNumberList(story: StoryOf<typeof stories>) {
    return mountStory(story).getComponent(FormNumberList);
}

type FormNumberListWrapper = ReturnType<typeof mountFormNumberList>;

function inputValues(wrapper: FormNumberListWrapper) {
    return wrapper.findAll(SELECTORS.INPUT).map((input) => (input.element as HTMLInputElement).value);
}

function lastEmittedValue(wrapper: FormNumberListWrapper) {
    return wrapper.emitted("input")!.at(-1);
}

describe("FormNumberList", () => {
    it("renders a number field per value", () => {
        const wrapper = mountFormNumberList(stories.TwoColumns);

        expect(inputValues(wrapper)).toEqual(["1", "2"]);
    });

    it("starts with one empty field that cannot be removed", () => {
        const wrapper = mountFormNumberList(stories.Unset);

        expect(wrapper.findAllComponents(FormNumber)).toHaveLength(1);
        expect(inputValues(wrapper)).toEqual([""]);
        expect(wrapper.find(SELECTORS.REMOVE).classes()).toContain("g-disabled");
    });

    it("emits the entered values as numbers", async () => {
        const wrapper = mountFormNumberList(stories.OneColumn);

        await wrapper.find(SELECTORS.ADD).trigger("click");
        await wrapper.findAll(SELECTORS.INPUT).at(1)!.setValue("3");

        expect(lastEmittedValue(wrapper)).toEqual([[1, 3]]);
    });

    it("removes a value", async () => {
        const wrapper = mountFormNumberList(stories.TwoColumns);

        await wrapper.findAll(SELECTORS.REMOVE).at(0)!.trigger("click");

        expect(lastEmittedValue(wrapper)).toEqual([[2]]);
        expect(wrapper.findAllComponents(FormNumber)).toHaveLength(1);
        expect(inputValues(wrapper)).toEqual(["2"]);
    });

    it("emits null once every field is empty", async () => {
        const wrapper = mountFormNumberList(stories.OneColumn);

        await wrapper.find(SELECTORS.INPUT).setValue("");

        expect(lastEmittedValue(wrapper)).toEqual([null]);
    });
});
