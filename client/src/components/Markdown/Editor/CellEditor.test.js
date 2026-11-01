import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import CellEditor from "./CellEditor.vue";

const MARKDOWN = "First\n```python\nx = 1\n```\nLast";
const ACTIONS_BUTTON = '[data-description="markdown cell actions button"]';

let container;

function mountTarget() {
    return mount(CellEditor, {
        props: { markdownText: MARKDOWN },
        attachTo: container,
        global: { stubs: { CellAdd: true, CellCode: true, SectionWrapper: true } },
    });
}

function cell(wrapper, index) {
    return wrapper.get(`[data-cell-index="${index}"]`);
}

async function chooseAction(wrapper, cellIndex, title) {
    await cell(wrapper, cellIndex).get('[data-description="markdown cell toggle button"]').trigger("click");
    await cell(wrapper, cellIndex).get(ACTIONS_BUTTON).trigger("click");
    const option = cell(wrapper, cellIndex).get(`[data-option-title="${title}"]`);
    option.element.focus();
    await option.trigger("keydown", { key: "Enter" });
    await wrapper.vm.$nextTick();
    await wrapper.vm.$nextTick();
}

describe("CellEditor.vue", () => {
    beforeEach(() => {
        container = document.createElement("div");
        document.body.appendChild(container);
    });

    afterEach(() => {
        container.remove();
    });

    it("swaps cells and emits the reordered markdown on Move Down", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        await chooseAction(wrapper, 0, "Move Down");
        const updates = wrapper.emitted("update");
        expect(updates).toHaveLength(1);
        expect(updates[0][0].indexOf("```python")).toBeLessThan(updates[0][0].indexOf("First"));
        wrapper.unmount();
    });

    it("moves focus with the cell when its neighbour is collapsed", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        await chooseAction(wrapper, 0, "Move Down");
        // The collapsed cell swapped into position 0 has no actions button to keep focus.
        expect(cell(wrapper, 0).find(ACTIONS_BUTTON).exists()).toBe(false);
        expect(document.activeElement).toBe(cell(wrapper, 1).get(ACTIONS_BUTTON).element);
        wrapper.unmount();
    });

    it("moves focus with the cell when its neighbour is expanded", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        await cell(wrapper, 2).get('[data-description="markdown cell toggle button"]').trigger("click");
        await chooseAction(wrapper, 1, "Move Down");
        expect(cell(wrapper, 1).find(ACTIONS_BUTTON).exists()).toBe(true);
        expect(document.activeElement).toBe(cell(wrapper, 2).get(ACTIONS_BUTTON).element);
        wrapper.unmount();
    });

    it("moves focus with the cell on Move Up", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        await chooseAction(wrapper, 2, "Move Up");
        expect(document.activeElement).toBe(cell(wrapper, 1).get(ACTIONS_BUTTON).element);
        wrapper.unmount();
    });
});
