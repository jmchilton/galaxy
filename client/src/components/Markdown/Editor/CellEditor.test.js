import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useServerMock } from "@/api/client/__mocks__";

import CellEditor from "./CellEditor.vue";

const { server, http } = useServerMock();

const MARKDOWN = "First\n```python\nx = 1\n```\nLast";

let container;

function mountTarget() {
    server.use(http.get("/api/plugins", ({ response }) => response(200).json([])));
    return mount(CellEditor, {
        props: { markdownText: MARKDOWN },
        attachTo: container,
        global: { stubs: { CellCode: true, SectionWrapper: true } },
    });
}

function cell(wrapper, index) {
    return wrapper.get(`[data-cell-index="${index}"]`);
}

async function chooseAction(wrapper, cellIndex, title) {
    await cell(wrapper, cellIndex).get('[data-description="markdown cell toggle button"]').trigger("click");
    await cell(wrapper, cellIndex).get('[data-description="markdown cell actions button"]').trigger("click");
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
});
