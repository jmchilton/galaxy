import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import DelayedInput from "./DelayedInput.vue";

const localVue = getLocalVue();

describe("DelayedInput.vue", () => {
    beforeEach(() => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    });

    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
    });
    enableAutoUnmount(afterEach);

    it("clears search text when the clear button is clicked", async () => {
        const wrapper = mount(DelayedInput, {
            global: localVue,
            props: { value: "test query" },
        });

        await wrapper.get("button.search-clear").trigger("click");
        await nextTick();

        expect(wrapper.find("input.g-form-input").exists()).toBe(true);
        expect(wrapper.get<HTMLInputElement>("input.g-form-input").element.value).toBe("");
    });
});
