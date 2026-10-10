import { composeStories } from "@storybook/vue3-vite";
import { useStoryMount } from "@tests/vitest/stories";
import type { VueWrapper } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it, vi } from "vitest";

import { SELECTION_STATES, type SelectionItem, type SelectionState } from "@/components/SelectionDialog/selectionTypes";

import * as FilesDialogStories from "./FilesDialog.stories";
import { directoryId, rootId } from "./testingData";

import SelectionDialog from "@/components/SelectionDialog/SelectionDialog.vue";

vi.mock("app");

const stories = composeStories(FilesDialogStories);
const mountStory = useStoryMount();

interface RowElement extends SelectionItem, Element {
    selectionState: SelectionState;
}

function getRenderedRows(wrapper: VueWrapper): RowElement[] {
    return wrapper.findComponent(SelectionDialog).props("items") as RowElement[];
}

async function openDirectoryById(wrapper: VueWrapper, id: string) {
    const directory = getRenderedRows(wrapper).find((row) => row.id === id);
    if (!directory) {
        throw new Error(`Directory with id ${id} not found`);
    }
    wrapper.findComponent(SelectionDialog).vm.$emit("onOpen", directory);
    await flushPromises();
}

async function navigateBack(wrapper: VueWrapper) {
    await wrapper.find("[data-description='selection dialog undo']").trigger("click");
    await flushPromises();
}

describe("FilesDialog, file mode", () => {
    // The root lists sources without checkboxes, so a source's own selection state isn't shown;
    // the SelectsAll play covers what is.
    it("marks a source selected at the root after selecting all inside it", async () => {
        const wrapper = mountStory(stories.MultipleFiles);
        await flushPromises();
        await openDirectoryById(wrapper, rootId);
        wrapper.findComponent(SelectionDialog).vm.$emit("onSelectAll");
        await flushPromises();
        await openDirectoryById(wrapper, directoryId);
        await navigateBack(wrapper);
        await navigateBack(wrapper);

        const rootNode = getRenderedRows(wrapper).find(({ id }) => id === rootId);
        expect(rootNode?.selectionState).toBe(SELECTION_STATES.SELECTED);
    });
});
