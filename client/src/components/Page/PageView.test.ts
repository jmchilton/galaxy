import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { ref } from "vue";
import type * as VueRouter from "vue-router";

import type { urlData } from "@/utils/url";

import PageView from "./PageView.vue";
import Heading from "@/components/Common/Heading.vue";
import PublishedItem from "@/components/Common/PublishedItem.vue";

vi.mock("@/composables/config", () => ({
    useConfig: vi.fn(() => ({
        config: ref({ enable_beta_markdown_export: false }),
        isConfigLoaded: ref(true),
    })),
}));

vi.mock("vue-router", async (importOriginal) => {
    const actual = await importOriginal<typeof VueRouter>();
    return {
        ...actual,
        useRouter: vi.fn(() => ({ push: vi.fn() })),
        useRoute: vi.fn(() => ({ params: {} })),
    };
});

const mockUrlData = vi.fn<typeof urlData>();
vi.mock("@/utils/url", () => ({
    urlData: (...args: Parameters<typeof urlData>) => mockUrlData(...args),
}));

const localVue = getLocalVue();

const PAGE_ID = "page-1";
const PAGE_DATA = {
    id: PAGE_ID,
    title: "Test Page",
    name: "Test Page",
    content: "# Hello World",
    content_format: "markdown",
    slug: "test-page",
    username: "testuser",
    model_class: "Page",
};

type PageViewProps = Pick<InstanceType<typeof PageView>["$props"], "pageId" | "embed" | "displayOnly" | "showHeading">;

function mountComponent(props: PageViewProps) {
    const pinia = createTestingPinia({ createSpy: vi.fn });
    onTestFinished(() => {
        disposePinia(pinia);
        if (getActivePinia() === pinia) {
            setActivePinia(undefined);
        }
    });
    return shallowMount(PageView, {
        props,
        global: {
            ...withPlugins(localVue, pinia),
            stubs: {
                ...localVue.stubs,
                FontAwesomeIcon: true,
                LoadingSpan: true,
                Markdown: true,
                PageHtml: true,
            },
        },
    });
}

afterEach(() => {
    vi.restoreAllMocks();
});
enableAutoUnmount(afterEach);

describe("PageView", () => {
    beforeEach(() => {
        vi.clearAllMocks();
        mockUrlData.mockResolvedValue(PAGE_DATA);
    });

    describe("default mode (published page with chrome)", () => {
        it("renders PublishedItem wrapper", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID });
            await flushPromises();

            expect(wrapper.findComponent(PublishedItem).exists()).toBe(true);
        });

        it("does not render embed container", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID });
            await flushPromises();

            expect(wrapper.find(".page-view.embed").exists()).toBe(false);
        });
    });

    describe("embed mode", () => {
        it("renders without PublishedItem wrapper", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, embed: true });
            await flushPromises();

            expect(wrapper.findComponent(PublishedItem).exists()).toBe(false);
            expect(wrapper.find(".page-view.embed").exists()).toBe(true);
        });

        it("does not show edit toolbar", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, embed: true });
            await flushPromises();

            expect(wrapper.find(".page-display-toolbar").exists()).toBe(false);
        });
    });

    describe("displayOnly mode", () => {
        it("renders without PublishedItem wrapper", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, displayOnly: true });
            await flushPromises();

            expect(wrapper.findComponent(PublishedItem).exists()).toBe(false);
            expect(wrapper.find(".page-view.embed").exists()).toBe(true);
        });

        it("shows edit toolbar with Edit Page button", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, displayOnly: true });
            await flushPromises();

            const toolbar = wrapper.find(".page-display-toolbar");
            expect(toolbar.exists()).toBe(true);

            const editBtn = wrapper.find('[data-description="page view edit button"]');
            expect(editBtn.exists()).toBe(true);
            expect(editBtn.text()).toContain("Edit Notebook");
        });

        it("shows page title in toolbar", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, displayOnly: true });
            await flushPromises();

            const toolbar = wrapper.find(".page-display-toolbar");
            expect(toolbar.text()).toContain("Test Page");
        });

        it("hides duplicate heading when displayOnly", async () => {
            const wrapper = mountComponent({ pageId: PAGE_ID, displayOnly: true, showHeading: true });
            await flushPromises();

            expect(wrapper.findComponent(Heading).exists()).toBe(false);
        });
    });
});
