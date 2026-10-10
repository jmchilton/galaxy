import { composeStories } from "@storybook/vue3-vite";
import { useStoryMount } from "@tests/vitest/stories";
import { BSpinner } from "bootstrap-vue";
import { describe, expect, it } from "vitest";

import * as DescribeObjectStoreStories from "./DescribeObjectStore.stories";

const stories = composeStories(DescribeObjectStoreStories);
const mountStory = useStoryMount();

// Class hooks for each way of naming the storage; Selenium finds `.display-os-by-name`.
const SELECTORS = {
    BY_NAME: ".display-os-by-name",
    BY_ID: ".display-os-by-id",
    DEFAULT: ".display-os-default",
};

function countDescriptionSpans(wrapper) {
    return Object.fromEntries(
        Object.entries(SELECTORS).map(([key, selector]) => [key, wrapper.findAll(selector).length]),
    );
}

describe("DescribeObjectStore.vue", () => {
    it.each([
        ["the default storage when it has no id", stories.DefaultStorage, { BY_NAME: 0, BY_ID: 0, DEFAULT: 1 }],
        ["the storage id when it has an id but no name", stories.StorageWithId, { BY_NAME: 0, BY_ID: 1, DEFAULT: 0 }],
        ["the storage name when it has one", stories.NamedPrivateStorage, { BY_NAME: 1, BY_ID: 0, DEFAULT: 0 }],
    ])("marks %s with its own class", (_description, story, expectedSpans) => {
        const wrapper = mountStory(story);

        expect(countDescriptionSpans(wrapper)).toEqual(expectedSpans);
    });

    it.each([
        ["no id", stories.DefaultStorage],
        ["an id", stories.StorageWithId],
        ["a name", stories.NamedPrivateStorage],
    ])("says no quota is configured, without a usage spinner, for storage with %s", (_description, story) => {
        const wrapper = mountStory(story);

        expect(wrapper.text()).toContain("Galaxy has no quota configured for this storage.");
        expect(wrapper.findComponent(BSpinner).exists()).toBe(false);
    });
});
