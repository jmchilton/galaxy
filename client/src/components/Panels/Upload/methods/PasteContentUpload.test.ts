import { getLocalVue } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { UploadMethodComponent } from "../types";

import PasteContentUpload from "./PasteContentUpload.vue";

vi.mock("@/composables/upload/uploadDefaults");

const localVue = getLocalVue();

const SELECTORS = {
    addDataset: '[data-test-id="add-another-dataset"]',
    sizeHeader: 'th[id^="g-table-field-size-"]',
    contentTextarea: (itemId: number) => `#paste-content-${itemId}`,
};

function mountPasteContentUpload() {
    return mount(PasteContentUpload as object, {
        localVue,
        pinia: createPinia(),
        propsData: {
            method: { id: "paste-content" },
            targetHistoryId: "hist_1",
            transient: true,
        },
    });
}

type Wrapper = ReturnType<typeof mountPasteContentUpload>;

function uploadedNames(wrapper: Wrapper): string[] {
    const prepared = (wrapper.vm as unknown as UploadMethodComponent).prepareUpload();
    return (prepared?.uploadItems ?? []).map((item) => item.name ?? "");
}

describe("PasteContentUpload", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
    });

    it("uploads pasted datasets in the order the size-sorted table shows", async () => {
        const wrapper = mountPasteContentUpload();
        await wrapper.find(SELECTORS.addDataset).trigger("click");
        await wrapper.find(SELECTORS.addDataset).trigger("click");
        await wrapper.vm.$nextTick();

        await wrapper.find(SELECTORS.contentTextarea(1)).setValue("xxx");
        await wrapper.find(SELECTORS.contentTextarea(2)).setValue("x");
        await wrapper.find(SELECTORS.contentTextarea(3)).setValue("xx");
        expect(uploadedNames(wrapper)).toEqual(["Pasted Dataset 1", "Pasted Dataset 2", "Pasted Dataset 3"]);

        await wrapper.find(SELECTORS.sizeHeader).trigger("click");
        expect(uploadedNames(wrapper)).toEqual(["Pasted Dataset 2", "Pasted Dataset 3", "Pasted Dataset 1"]);
    });
});
