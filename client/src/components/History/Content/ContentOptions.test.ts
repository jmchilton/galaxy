import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, suppressLucideVue2Deprecation } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContentOptions from "./ContentOptions.vue";

const localVue = getLocalVue();

const NOT_EDITABLE_STATES = ["discarded", "new", "upload", "queued", "running", "waiting"];

function mountContentOptions(state: string) {
    return mount(ContentOptions as object, {
        propsData: {
            isDataset: true,
            isHistoryItem: true,
            state,
            itemUrls: { edit: "/datasets/item-id/edit", display: "/datasets/item-id/preview" },
        },
        localVue,
        pinia: createTestingPinia({ createSpy: vi.fn }),
        attachTo: document.body,
    });
}

describe("ContentOptions edit button", () => {
    beforeEach(() => {
        suppressLucideVue2Deprecation();
    });

    it.each(NOT_EDITABLE_STATES)("is disabled for a %s dataset", async (state) => {
        const wrapper = mountContentOptions(state);
        const editButton = wrapper.find(".edit-btn");
        expect(editButton.attributes("aria-disabled")).toBe("true");
        await editButton.trigger("click");
        expect(wrapper.emitted("edit")).toBeUndefined();
        wrapper.unmount();
    });

    it.each([
        ["discarded", "This dataset is not yet editable."],
        ["ok", "Edit attributes"],
    ])("describes a %s dataset's edit button with a tooltip", async (state, expectedTooltip) => {
        const wrapper = mountContentOptions(state);
        await flushPromises();
        const tooltipId = wrapper.find(".edit-btn").attributes("aria-describedby");
        expect(tooltipId).toBeDefined();
        expect(wrapper.find(`#${tooltipId}[role="tooltip"]`).text()).toBe(expectedTooltip);
        wrapper.unmount();
    });

    it("is enabled for an ok dataset", async () => {
        const wrapper = mountContentOptions("ok");
        const editButton = wrapper.find(".edit-btn");
        expect(editButton.attributes("aria-disabled")).toBeUndefined();
        await editButton.trigger("click");
        expect(wrapper.emitted("edit")).toHaveLength(1);
        wrapper.unmount();
    });
});
