import { getLocalVue } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import WorkflowHelpDisplay from "./WorkflowHelpDisplay.vue";

const localVue = getLocalVue();

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

describe("WorkflowHelpDisplay", () => {
    it("renders readme and help markdown through v-sanitize-html with the links profile", () => {
        const wrapper = mount(WorkflowHelpDisplay as object, {
            localVue,
            propsData: {
                workflow: {
                    readme: "**Readme** with [a link](https://galaxyproject.org) and <em>raw</em>",
                    help: "Help *text*",
                },
            },
        });

        const calls = vi.mocked(sanitizeHtml).mock.calls;
        expect(calls).toHaveLength(2);
        const [readmeHtml, readmeProfile] = calls[0]!;
        expect(readmeProfile).toBe("links");
        expect(readmeHtml).toContain("<strong>Readme</strong>");
        expect(readmeHtml).toContain('target="_blank"');
        expect(readmeHtml).toContain("&lt;em&gt;raw&lt;/em&gt;");
        expect(calls[1]![1]).toBe("links");

        const rendered = wrapper.findAll(".container .sanitized");
        expect(rendered).toHaveLength(2);
        expect(rendered.at(1)!.html()).toContain("<em>text</em>");
    });
});
