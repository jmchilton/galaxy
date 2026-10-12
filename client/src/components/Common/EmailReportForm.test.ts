import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import EmailReportForm from "./EmailReportForm.vue";

const localVue = getLocalVue();
const sanitizeHtmlMock = vi.mocked(sanitizeHtml);

beforeEach(() => sanitizeHtmlMock.mockClear());
afterEach(() => sanitizeHtmlMock.mockClear());
enableAutoUnmount(afterEach);

describe("EmailReportForm", () => {
    it("renders report results through v-sanitize-html with the links profile", async () => {
        const pinia = createTestingPinia({ createSpy: vi.fn });
        onTestFinished(() => disposePinia(pinia));
        const submit = vi.fn(async () => [["Created [issue #1](https://github.com/org/repo/issues/1)", "success"]]);
        const wrapper = mount(EmailReportForm, {
            global: withPlugins(localVue, pinia),
            props: { submit },
        });

        await wrapper.get("#email-report-submit").trigger("click");
        await flushPromises();

        const call = sanitizeHtmlMock.mock.calls.find(([html]) => html?.includes("issue #1"));
        expect(call?.[1]).toBe("links");
        expect(call?.[0]).toContain('href="https://github.com/org/repo/issues/1" target="_blank"');
        expect(wrapper.get(".alert a").text()).toBe("issue #1");
    });
});
