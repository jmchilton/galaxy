import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import FormMessage from "./FormMessage.vue";

vi.mock("app");

const localVue = getLocalVue();

function mountMessage() {
    return mount(FormMessage, {
        props: {
            message: "test message",
            variant: "danger",
            persistent: true,
            timeout: 1000,
        },
        global: localVue,
    });
}

describe("FormMessage", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
    });
    enableAutoUnmount(afterEach);

    it("shows a persistent danger message", () => {
        const wrapper = mountMessage();

        expect(wrapper.findAll(".alert-danger")).toHaveLength(1);
        expect(wrapper.get(".alert").text()).toBe("test message");
    });

    it("expires a transient message and shows the next message", async () => {
        const wrapper = mountMessage();
        await wrapper.setProps({
            persistent: false,
            variant: "info",
            message: "new message",
        });

        expect(wrapper.findAll(".alert-info")).toHaveLength(1);
        expect(wrapper.get(".alert").text()).toBe("new message");

        vi.advanceTimersByTime(1000);
        await nextTick();
        expect(wrapper.findAll(".alert-info")).toHaveLength(0);

        await wrapper.setProps({
            variant: "warning",
            message: "last message",
        });
        expect(wrapper.get(".alert").text()).toBe("last message");
    });
});
