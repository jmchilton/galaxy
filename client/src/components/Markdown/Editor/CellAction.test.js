import { mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CellAction from "./CellAction.vue";
import CellOption from "./CellOption.vue";

const { confirm } = vi.hoisted(() => ({ confirm: vi.fn() }));

vi.mock("@/composables/confirmDialog", () => ({
    useConfirmDialog: () => ({ confirm }),
}));

let container;

// Dispatch a full key press and return the keydown event, to check whether its default was prevented.
function pressKey(element, key) {
    const keydown = new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
    element.dispatchEvent(keydown);
    element.dispatchEvent(new KeyboardEvent("keyup", { key, bubbles: true, cancelable: true }));
    return keydown;
}

function mountTarget(props = {}) {
    return mount(CellAction, {
        props: { cellIndex: 1, cellTotal: 3, name: "markdown", ...props },
        attachTo: container,
    });
}

async function openMenu(wrapper) {
    const button = wrapper.get("button");
    await button.trigger("click");
    const menu = wrapper.get(".popper-element");
    expect(menu.isVisible()).toBe(true);
    return { button, menu };
}

function findOption(wrapper, title) {
    const option = wrapper.findAllComponents(CellOption).find((candidate) => candidate.props("title") === title);
    expect(option).toBeTruthy();
    return option;
}

describe("CellAction.vue", () => {
    beforeEach(() => {
        container = document.createElement("div");
        document.body.appendChild(container);
        confirm.mockReset();
    });

    afterEach(() => {
        container.remove();
    });

    it("lists move options that fit the cell position", async () => {
        const first = mountTarget({ cellIndex: 0, cellTotal: 2 });
        await first.vm.$nextTick();
        expect(first.findAllComponents(CellOption).map((option) => option.props("title"))).toEqual([
            "Clone",
            "Delete",
            "Move Down",
        ]);
        first.unmount();

        const last = mountTarget({ cellIndex: 1, cellTotal: 2 });
        await last.vm.$nextTick();
        expect(last.findAllComponents(CellOption).map((option) => option.props("title"))).toEqual([
            "Clone",
            "Delete",
            "Move Up",
        ]);
        last.unmount();
    });

    it("emits and closes the menu when an option is clicked", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        const { menu } = await openMenu(wrapper);
        await findOption(wrapper, "Clone").trigger("click");
        expect(wrapper.emitted("clone")).toHaveLength(1);
        expect(menu.isVisible()).toBe(false);
        wrapper.unmount();
    });

    it("emits and closes the menu when an option is chosen with Enter or Space", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();

        let { menu } = await openMenu(wrapper);
        await findOption(wrapper, "Move Up").trigger("keydown", { key: "Enter" });
        expect(wrapper.emitted("move")).toEqual([["up"]]);
        expect(menu.isVisible()).toBe(false);

        ({ menu } = await openMenu(wrapper));
        const moveDown = findOption(wrapper, "Move Down");
        await moveDown.trigger("keydown", { key: " " });
        expect(menu.isVisible()).toBe(true);
        await moveDown.trigger("keyup", { key: " " });
        expect(wrapper.emitted("move")).toEqual([["up"], ["down"]]);
        expect(menu.isVisible()).toBe(false);
        wrapper.unmount();
    });

    it("returns focus to the actions button when an option is chosen with Enter or Space", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();

        for (const [key, title] of [
            ["Enter", "Clone"],
            [" ", "Move Down"],
        ]) {
            const { button, menu } = await openMenu(wrapper);
            const option = findOption(wrapper, title);
            option.element.focus();
            expect(document.activeElement).toBe(option.element);
            const event = pressKey(option.element, key);
            await wrapper.vm.$nextTick();
            // Unprevented, Space scrolls the page and Enter activates the trigger that now has focus.
            expect(event.defaultPrevented).toBe(true);
            expect(menu.isVisible()).toBe(false);
            expect(document.activeElement).toBe(button.element);
        }
        expect(wrapper.emitted("clone")).toHaveLength(1);
        expect(wrapper.emitted("move")).toEqual([["down"]]);
        wrapper.unmount();
    });

    it("returns focus to the actions button when a focused option is clicked", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        const { button, menu } = await openMenu(wrapper);
        const option = findOption(wrapper, "Clone");
        option.element.focus();
        await option.trigger("click");
        expect(menu.isVisible()).toBe(false);
        expect(document.activeElement).toBe(button.element);
        wrapper.unmount();
    });

    it("keeps the menu open when a Space press started on another option is released", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        const { menu } = await openMenu(wrapper);
        await findOption(wrapper, "Clone").trigger("keydown", { key: " " });
        await findOption(wrapper, "Delete").trigger("keyup", { key: " " });
        expect(wrapper.emitted("clone")).toBeFalsy();
        expect(confirm).not.toHaveBeenCalled();
        expect(menu.isVisible()).toBe(true);
        wrapper.unmount();
    });

    it("asks for confirmation before deleting", async () => {
        const wrapper = mountTarget();
        await wrapper.vm.$nextTick();
        await openMenu(wrapper);

        confirm.mockResolvedValueOnce(false);
        await findOption(wrapper, "Delete").trigger("click");
        await vi.waitFor(() => expect(confirm).toHaveBeenCalledTimes(1));
        expect(wrapper.emitted("delete")).toBeFalsy();

        await openMenu(wrapper);
        confirm.mockResolvedValueOnce(true);
        await findOption(wrapper, "Delete").trigger("click");
        await vi.waitFor(() => expect(wrapper.emitted("delete")).toHaveLength(1));
        wrapper.unmount();
    });
});
