import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import NodeInvocationText from "./NodeInvocationText.vue";

const sanitizeSpy = vi.mocked(sanitizeHtml);
const originalSanitizeImplementation = sanitizeSpy.getMockImplementation();

beforeEach(() => {
    sanitizeSpy.mockClear();
    sanitizeSpy.mockImplementation((html) => `<span class="sanitized">${html}</span>`);
});

afterEach(() => {
    sanitizeSpy.mockReset();
    if (originalSanitizeImplementation) {
        sanitizeSpy.mockImplementation(originalSanitizeImplementation);
    }
});
// afterEach runs in reverse order: unmount before restoring the sanitizer.
enableAutoUnmount(afterEach);

describe("NodeInvocationText", () => {
    it("renders input step text through v-sanitize-html", () => {
        const wrapper = shallowMount(NodeInvocationText as object, {
            localVue: getLocalVue(),
            propsData: { invocationStep: { type: "data_input", nodeText: "1: <b>input.fastq</b>" } },
        });

        expect(sanitizeHtml).toHaveBeenCalledWith(expect.any(String), "default");
        expect(wrapper.find(".sanitized").exists()).toBe(true);
    });
});
