import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import ButtonPlain from "./ButtonPlain.vue";

function dispatchKey(element, type, key) {
    const event = new KeyboardEvent(type, { key, bubbles: true, cancelable: true });
    element.dispatchEvent(event);
    return event;
}

// Listen the way consumers do, rather than reading emitted(), which also records the native click.
function mountTarget() {
    const onClick = vi.fn();
    const wrapper = mount(ButtonPlain, { attrs: { onClick }, slots: { default: "Label" } });
    return { wrapper, onClick };
}

describe("ButtonPlain.vue", () => {
    it("renders a focusable button with its slot content", () => {
        const { wrapper } = mountTarget();
        expect(wrapper.attributes("role")).toBe("button");
        expect(wrapper.attributes("tabindex")).toBe("0");
        expect(wrapper.text()).toBe("Label");
    });

    it("activates once when clicked", async () => {
        const { wrapper, onClick } = mountTarget();
        await wrapper.trigger("click");
        expect(onClick).toHaveBeenCalledTimes(1);
    });

    it("activates once for a full Enter or Space key press", () => {
        const { wrapper, onClick } = mountTarget();
        for (const key of ["Enter", " "]) {
            dispatchKey(wrapper.element, "keydown", key);
            dispatchKey(wrapper.element, "keyup", key);
        }
        expect(onClick).toHaveBeenCalledTimes(2);
    });

    it("prevents the page from scrolling on Space", () => {
        const { wrapper } = mountTarget();
        expect(dispatchKey(wrapper.element, "keydown", " ").defaultPrevented).toBe(true);
    });

    // A handler that moves focus must not leave the key's default action or keyup to activate the newly focused control.
    it("prevents Enter's default action", () => {
        const { wrapper } = mountTarget();
        expect(dispatchKey(wrapper.element, "keydown", "Enter").defaultPrevented).toBe(true);
    });

    it("activates on Space keyup, not keydown, like a native button", () => {
        const { wrapper, onClick } = mountTarget();
        dispatchKey(wrapper.element, "keydown", " ");
        expect(onClick).not.toHaveBeenCalled();
        dispatchKey(wrapper.element, "keyup", " ");
        expect(onClick).toHaveBeenCalledTimes(1);
    });
});
