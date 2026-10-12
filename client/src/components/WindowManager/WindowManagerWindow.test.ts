import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { useWindowManagerStore } from "@/stores/windowManagerStore";

import WindowManagerWindow from "./WindowManagerWindow.vue";

const localVue = getLocalVue();

// happy-dom does not implement pointer capture, so stub it. Capturing the
// pointer is what keeps drag/resize alive when the cursor crosses an iframe
// (the center frame or the window's own body), so we assert on these calls.
const setPointerCapture = vi.fn();
let originalPointerCapture: PropertyDescriptor | undefined;

function pointerEvent(type: string, options: PointerEventInit = {}) {
    return new PointerEvent(type, { bubbles: true, cancelable: true, button: 0, pointerId: 7, ...options });
}

function mountWindow() {
    const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
    onTestFinished(() => disposePinia(pinia));
    const store = useWindowManagerStore(pinia);
    store.add({ title: "GalaxyAI", url: "/galaxyai", x: 50, y: 60, width: 400, height: 300 });
    const win = store.windows[0]!;
    const wrapper = mount(WindowManagerWindow, {
        global: withPlugins(localVue, pinia),
        props: { window: win },
    });
    return { wrapper, win };
}

describe("WindowManagerWindow", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        originalPointerCapture = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "setPointerCapture");
        Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
            configurable: true,
            writable: true,
            value: setPointerCapture,
        });
    });

    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
        setPointerCapture.mockClear();
        if (originalPointerCapture) {
            Object.defineProperty(HTMLElement.prototype, "setPointerCapture", originalPointerCapture);
        } else {
            Reflect.deleteProperty(HTMLElement.prototype, "setPointerCapture");
        }
    });

    // Unmount before clearing the store's save timer and restoring the pointer stub.
    enableAutoUnmount(afterEach);

    it("resizes with the pointer and captures it on the handle", () => {
        const { wrapper, win } = mountWindow();
        const handle = wrapper.get(".window-manager-resize-handle");

        handle.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 450, clientY: 360 }));
        expect(setPointerCapture).toHaveBeenCalledWith(7);

        document.dispatchEvent(pointerEvent("pointermove", { clientX: 550, clientY: 410 }));
        expect(win.width).toBe(500);
        expect(win.height).toBe(350);

        document.dispatchEvent(pointerEvent("pointerup", { clientX: 550, clientY: 410 }));
        document.dispatchEvent(pointerEvent("pointermove", { clientX: 650, clientY: 460 }));
        expect(win.width).toBe(500);
        expect(win.height).toBe(350);
    });

    it("drags with the pointer and captures it on the header", () => {
        const { wrapper, win } = mountWindow();
        const header = wrapper.get(".window-manager-window-header");

        header.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 200, clientY: 80 }));
        expect(setPointerCapture).toHaveBeenCalledWith(7);

        document.dispatchEvent(pointerEvent("pointermove", { clientX: 230, clientY: 120 }));
        expect(win.x).toBe(80);
        expect(win.y).toBe(100);

        document.dispatchEvent(pointerEvent("pointerup", { clientX: 230, clientY: 120 }));
        document.dispatchEvent(pointerEvent("pointermove", { clientX: 300, clientY: 200 }));
        expect(win.x).toBe(80);
        expect(win.y).toBe(100);
    });

    it("stops resizing when the pointer is cancelled", () => {
        const { wrapper, win } = mountWindow();
        const handle = wrapper.get(".window-manager-resize-handle");

        handle.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 450, clientY: 360 }));
        document.dispatchEvent(pointerEvent("pointermove", { clientX: 550, clientY: 410 }));
        expect(win.width).toBe(500);

        document.dispatchEvent(pointerEvent("pointercancel", { clientX: 550, clientY: 410 }));
        document.dispatchEvent(pointerEvent("pointermove", { clientX: 650, clientY: 460 }));
        expect(win.width).toBe(500);
        expect(win.height).toBe(350);
    });

    it("does not start a drag from the window controls", () => {
        const { wrapper, win } = mountWindow();
        const controls = wrapper.get(".window-manager-window-controls");

        controls.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 420, clientY: 70 }));
        document.dispatchEvent(pointerEvent("pointermove", { clientX: 500, clientY: 200 }));
        expect(win.x).toBe(50);
        expect(win.y).toBe(60);
    });

    it("ignores a second pointer while dragging", () => {
        const { wrapper, win } = mountWindow();
        const header = wrapper.get(".window-manager-window-header");

        header.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 200, clientY: 80 }));
        header.element.dispatchEvent(pointerEvent("pointerdown", { pointerId: 9, clientX: 300, clientY: 200 }));

        document.dispatchEvent(pointerEvent("pointermove", { pointerId: 9, clientX: 400, clientY: 300 }));
        expect(win.x).toBe(50);
        expect(win.y).toBe(60);

        document.dispatchEvent(pointerEvent("pointermove", { clientX: 230, clientY: 120 }));
        expect(win.x).toBe(80);
        expect(win.y).toBe(100);

        document.dispatchEvent(pointerEvent("pointerup", { clientX: 230, clientY: 120 }));
    });

    it("does not steal focus when clicking the controls of an unfocused window", () => {
        const pinia = createTestingPinia({ createSpy: vi.fn, stubActions: false });
        onTestFinished(() => disposePinia(pinia));
        const store = useWindowManagerStore(pinia);
        store.add({ title: "First", url: "/a", x: 50, y: 60, width: 400, height: 300 });
        store.add({ title: "Second", url: "/b" });
        const first = store.windows[0]!;
        const second = store.windows[1]!;
        const wrapper = mount(WindowManagerWindow, {
            global: withPlugins(localVue, pinia),
            props: { window: first },
        });
        expect(store.focusedId).toBe(second.id);

        // a real click delivers pointerdown plus a compatibility mousedown;
        // neither may bubble to the root focus handler from the controls
        const controls = wrapper.get(".window-manager-window-controls");
        controls.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 420, clientY: 70 }));
        controls.element.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
        expect(store.focusedId).toBe(second.id);

        const header = wrapper.get(".window-manager-window-header");
        header.element.dispatchEvent(pointerEvent("pointerdown", { clientX: 200, clientY: 80 }));
        expect(store.focusedId).toBe(first.id);
        document.dispatchEvent(pointerEvent("pointerup", { clientX: 200, clientY: 80 }));
    });
});
