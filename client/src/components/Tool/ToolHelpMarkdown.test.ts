import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, nth, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import ToolHelpMarkdown from "./ToolHelpMarkdown.vue";

vi.mock("@/onload/loadConfig", () => ({ getAppRoot: () => "/galaxy/" }));

describe("ToolHelpMarkdown", () => {
    beforeEach(() => {
        vi.mocked(sanitizeHtml).mockClear();
    });
    afterEach(() => {
        vi.mocked(sanitizeHtml).mockClear();
    });
    enableAutoUnmount(afterEach);

    it("renders help through v-sanitize-html with the markdown profile", async () => {
        const pinia = createTestingPinia({ createSpy: vi.fn });
        onTestFinished(() => disposePinia(pinia));
        const wrapper = mount(ToolHelpMarkdown, {
            global: { ...withPlugins(getLocalVue(), pinia), stubs: { MarkdownHelpPopovers: true } },
            props: { content: "See [docs](https://example.org), a [term](gxhelp://tool) and <b>raw</b>" },
        });
        await flushPromises();

        const [html, profile] = nth(vi.mocked(sanitizeHtml).mock.calls, 0);
        expect(profile).toBe("markdown");
        expect(html).toContain('href="https://example.org" target="_blank"');
        expect(html).toContain("&lt;b&gt;raw&lt;/b&gt;");
        const links = wrapper.findAll("a");
        expect(nth(links, 1).attributes("href")).toBe("/galaxy/help/terms/tool");
    });
});
