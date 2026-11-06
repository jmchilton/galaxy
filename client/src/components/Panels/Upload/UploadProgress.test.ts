import { currentPagerPage, getLocalVue, goToPage, pagerPages } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";
import { defineComponent, h } from "vue";

import { makePastedItem } from "@/composables/upload/testHelpers/uploadFixtures";

import { useUploadState } from "./uploadState";

import UploadProgress from "./UploadProgress.vue";

const SELECTORS = {
    ROW: ".upload-row-stub",
};

const UploadFileRowStub = defineComponent({
    props: { file: { type: Object, required: true } },
    setup(props) {
        return () => h("div", { class: "upload-row-stub", "data-name": props.file.name });
    },
});

function addUploads(count: number) {
    const { addUploadItem } = useUploadState();
    return Array.from({ length: count }, (_, index) => addUploadItem(makePastedItem({ name: `upload-${index + 1}` })));
}

function mountProgress() {
    const localVue = getLocalVue();
    return mount(UploadProgress as object, {
        global: {
            ...localVue,
            stubs: { ...localVue.stubs, UploadFileRow: UploadFileRowStub },
        },
    });
}

describe("UploadProgress", () => {
    // Upload state is a module singleton
    beforeEach(() => useUploadState().clearAll());

    it("pages through the uploads", async () => {
        addUploads(30);
        const wrapper = mountProgress();

        expect(wrapper.findAll(SELECTORS.ROW)).toHaveLength(24);
        expect(currentPagerPage(wrapper)).toBe("1");

        await goToPage(wrapper, 2);

        expect(currentPagerPage(wrapper)).toBe("2");
        expect(wrapper.findAll(SELECTORS.ROW)).toHaveLength(6);
    });

    it("leaves the emptied page when Clear Completed removes it", async () => {
        const ids = addUploads(30);
        ids.slice(10).forEach((id) => useUploadState().setStatus(id, "completed"));
        const wrapper = mountProgress();
        await goToPage(wrapper, 2);

        const clearCompleted = wrapper.findAll("button").find((button) => button.text() === "Clear Completed");
        await clearCompleted!.trigger("click");

        expect(pagerPages(wrapper)).toEqual([]);
        expect(wrapper.findAll(SELECTORS.ROW)).toHaveLength(10);
    });
});
