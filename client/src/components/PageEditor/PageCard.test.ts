import { createTestingPinia } from "@pinia/testing";
import { getFakeRegisteredUser } from "@tests/test-data";
import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

import type { RegisteredUser } from "@/api";
import { useUserStore } from "@/stores/userStore";

import { FAKE_PAGE_SUMMARY, FAKE_PAGE_UNTITLED } from "./testData";

import PageCard from "./PageCard.vue";

const localVue = getLocalVue();

function getSelector(selector: "title" | "revision" | "time" | "view" | "edit" | "share" | "owner", pageId: string) {
    if (selector === "title") {
        return `#g-card-title-link-page-${pageId}`;
    } else if (selector === "revision") {
        return `#g-card-badge-notebook-revisions-count-page-${pageId}`;
    } else if (selector === "time") {
        return `#g-card-page-${pageId}-update-time`;
    } else if (selector === "view") {
        return `#g-card-action-view-notebook-page-${pageId}`;
    } else if (selector === "edit") {
        return `#g-card-action-edit-notebook-page-${pageId}`;
    }
    if (selector === "share") {
        return `#g-card-action-share-access-management-page-${pageId}`;
    } else if (selector === "owner") {
        return `#g-card-badge-owned-by-other-user-page-${pageId}`;
    }
    throw new Error(`Unknown selector: ${selector}`);
}

describe("PageCard", () => {
    it("displays page title which edits notebook on click", async () => {
        const wrapper = mount(PageCard as object, {
            localVue,
            propsData: { page: FAKE_PAGE_SUMMARY },
            pinia: createTestingPinia({ createSpy: vi.fn }),
        });

        const title = wrapper.find(getSelector("title", FAKE_PAGE_SUMMARY.id));
        expect(title.text()).toBe("My Analysis");
        expect(title.attributes("title")).toBe("Edit Notebook");

        // Click to emit edit event
        await title.trigger("click");
        expect(wrapper.emitted("edit")).toBeTruthy();
    });

    it("shows 'Untitled Notebook' when title is empty", () => {
        const wrapper = mount(PageCard as object, {
            localVue,
            propsData: { page: FAKE_PAGE_UNTITLED },
            pinia: createTestingPinia({ createSpy: vi.fn }),
        });

        const title = wrapper.find(getSelector("title", FAKE_PAGE_UNTITLED.id));
        expect(title.text()).toBe("Untitled Notebook");
    });

    it("displays update time badge and revision count", () => {
        const wrapper = mount(PageCard as object, {
            localVue,
            propsData: { page: FAKE_PAGE_SUMMARY },
            pinia: createTestingPinia({ createSpy: vi.fn }),
        });

        expect(wrapper.find(getSelector("time", FAKE_PAGE_SUMMARY.id)).exists()).toBe(true);

        const revisionBadge = wrapper.find(getSelector("revision", FAKE_PAGE_SUMMARY.id));
        expect(revisionBadge.exists()).toBe(true);
        expect(revisionBadge.text()).toBe(
            `${FAKE_PAGE_SUMMARY.revision_ids.length} Revision${FAKE_PAGE_SUMMARY.revision_ids.length !== 1 ? "s" : ""}`,
        );
    });

    it("emits 'view' and 'select' operations correctly", async () => {
        const wrapper = mount(PageCard as object, {
            localVue,
            propsData: { page: FAKE_PAGE_SUMMARY },
            pinia: createTestingPinia({ createSpy: vi.fn }),
        });

        const viewButton = wrapper.find(getSelector("view", FAKE_PAGE_SUMMARY.id));
        await viewButton.trigger("click");
        expect(wrapper.emitted("view")).toBeTruthy();

        const editButton = wrapper.find(getSelector("edit", FAKE_PAGE_SUMMARY.id));
        await editButton.trigger("click");
        expect(wrapper.emitted("edit")).toBeTruthy();
    });
});

describe("PageCard actions", () => {
    const owner = getFakeRegisteredUser({ username: FAKE_PAGE_SUMMARY.username });

    function mountCard(user?: RegisteredUser) {
        const global = getLocalVue();
        const userStore = useUserStore();
        if (user) {
            userStore.setCurrentUser(user);
        }
        const wrapper = mount(PageCard, {
            global,
            props: { page: { ...FAKE_PAGE_SUMMARY } },
        });
        return { wrapper, userStore };
    }

    it("shows Share and Publish when the owner is loaded before mounting", () => {
        const { wrapper } = mountCard(owner);
        expect(wrapper.find(getSelector("owner", FAKE_PAGE_SUMMARY.id)).exists()).toBe(false);
        expect(wrapper.get(getSelector("share", FAKE_PAGE_SUMMARY.id)).attributes("href")).toBe(
            `/pages/sharing?id=${FAKE_PAGE_SUMMARY.id}`,
        );
    });

    it("shows Share and Publish once the current user loads after mount", async () => {
        const { wrapper, userStore } = mountCard();
        expect(wrapper.find(getSelector("owner", FAKE_PAGE_SUMMARY.id)).exists()).toBe(true);
        expect(wrapper.find(getSelector("share", FAKE_PAGE_SUMMARY.id)).exists()).toBe(false);

        userStore.setCurrentUser(owner);
        await wrapper.vm.$nextTick();

        expect(wrapper.find(getSelector("owner", FAKE_PAGE_SUMMARY.id)).exists()).toBe(false);
        expect(wrapper.find(getSelector("share", FAKE_PAGE_SUMMARY.id)).exists()).toBe(true);
    });

    it("hides Share and Publish when the current user changes to a non-owner", async () => {
        const { wrapper, userStore } = mountCard(owner);
        expect(wrapper.find(getSelector("share", FAKE_PAGE_SUMMARY.id)).exists()).toBe(true);

        userStore.setCurrentUser({ ...owner, id: "other", username: "other" });
        await wrapper.vm.$nextTick();

        expect(wrapper.find(getSelector("owner", FAKE_PAGE_SUMMARY.id)).exists()).toBe(true);
        expect(wrapper.find(getSelector("share", FAKE_PAGE_SUMMARY.id)).exists()).toBe(false);
    });

    it("updates Edit and Share actions when a page is deleted and restored", async () => {
        const { wrapper } = mountCard(owner);
        const editSelector = getSelector("edit", FAKE_PAGE_SUMMARY.id);
        const shareSelector = getSelector("share", FAKE_PAGE_SUMMARY.id);
        expect(wrapper.get(editSelector).attributes("aria-disabled")).toBeUndefined();
        expect(wrapper.get(shareSelector).text()).toBe("Share and Publish");

        await wrapper.setProps({ page: { ...FAKE_PAGE_SUMMARY, deleted: true } });
        expect(wrapper.get(editSelector).attributes("aria-disabled")).toBe("true");
        expect(wrapper.get(editSelector).attributes("title")).toBe("This Notebook is deleted");
        expect(wrapper.find(shareSelector).exists()).toBe(false);
        await wrapper.get(editSelector).trigger("click");
        expect(wrapper.emitted("edit")).toBeUndefined();

        await wrapper.setProps({ page: { ...FAKE_PAGE_SUMMARY, deleted: false } });
        expect(wrapper.get(editSelector).attributes("aria-disabled")).toBeUndefined();
        expect(wrapper.get(editSelector).attributes("title")).toBe("Edit Notebook");
        expect(wrapper.get(shareSelector).text()).toBe("Share and Publish");
        await wrapper.get(editSelector).trigger("click");
        expect(wrapper.emitted("edit")).toHaveLength(1);
    });
});
