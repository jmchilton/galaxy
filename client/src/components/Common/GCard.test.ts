import { createTestingPinia } from "@pinia/testing";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import { sanitizeHtml } from "@/directives/sanitizeHtml";

import GCard from "./GCard.vue";

const localVue = getLocalVue();

function mountCard(propsData: object) {
    return mount(GCard as object, {
        propsData: { id: "card", title: "Card", ...propsData },
        localVue,
        pinia: createTestingPinia({ createSpy: vi.fn }),
        stubs: { FontAwesomeIcon: true },
    });
}

describe("GCard", () => {
    it("renders a full description as markdown through v-sanitize-html with the links profile", () => {
        vi.mocked(sanitizeHtml).mockClear();
        mountCard({
            description: "Some **bold** text, a [link](https://example.org) and <b>raw</b>",
            fullDescription: true,
        });

        const [html, profile] = vi.mocked(sanitizeHtml).mock.calls[0]!;
        expect(profile).toBe("links");
        expect(html).toContain("<strong>bold</strong>");
        expect(html).toContain('href="https://example.org" target="_blank"');
        expect(html).toContain("&lt;b&gt;raw&lt;/b&gt;");
    });

    it("allows clicking actions that only navigate", async () => {
        const handler = vi.fn();
        const wrapper = mountCard({
            secondaryActions: [
                { id: "download", label: "Download", title: "Download", href: "/download" },
                { id: "copy", label: "Copy", title: "Copy", handler },
            ],
            primaryActions: [{ id: "edit", label: "Edit", title: "Edit", href: "/edit" }],
        });
        await wrapper.find("#g-card-action-download-card").trigger("click");
        await wrapper.find("#g-card-action-edit-card").trigger("click");
        expect(handler).not.toHaveBeenCalled();
        await wrapper.find("#g-card-action-copy-card").trigger("click");
        expect(handler).toHaveBeenCalledOnce();
    });

    it("renders the clear-title button only when canClearTitle is set", () => {
        expect(mountCard({}).find(".g-card-clear-title").exists()).toBe(false);
        expect(mountCard({ canClearTitle: true }).find(".g-card-clear-title").exists()).toBe(true);
    });

    it("styles the clear-title button as a red icon-only button, like the rename button", () => {
        const button = mountCard({ canClearTitle: true }).get(".g-card-clear-title");
        expect(button.classes()).toEqual(expect.arrayContaining(["g-red", "g-icon-only", "g-transparent"]));
    });

    it("emits clearTitle when the clear-title button is clicked", async () => {
        const wrapper = mountCard({ canClearTitle: true });
        await wrapper.get(".g-card-clear-title").trigger("click");
        expect(wrapper.emitted("clearTitle")).toHaveLength(1);
    });
});
