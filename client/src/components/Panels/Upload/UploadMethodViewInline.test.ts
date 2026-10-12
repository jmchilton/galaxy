import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { createPinia, disposePinia } from "pinia";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { computed, h, ref } from "vue";

import UploadMethodViewInline from "./UploadMethodViewInline.vue";

vi.mock("./uploadMethodRegistry", () => ({
    useFilteredUploadMethods: () =>
        computed(() => [
            {
                id: "paste-links",
                name: "Paste Links",
                description: "Paste URLs",
                icon: "link",
                component: { name: "PasteLinks", render: () => h("div", { class: "paste-links-method" }) },
            },
        ]),
}));

vi.mock("@/composables/history/useTargetHistoryUploadState", () => ({
    useTargetHistoryUploadState: () => ({ uploadBlockReason: ref(null) }),
}));

vi.mock("@/composables/upload/useUploadSubmission", () => ({
    useUploadSubmission: () => ({ submitPreparedUpload: vi.fn() }),
}));

const localVue = getLocalVue();

describe("UploadMethodViewInline", () => {
    afterEach(() => {
        vi.restoreAllMocks();
    });
    enableAutoUnmount(afterEach);

    it("renders the selected method component without making it reactive", () => {
        const warn = vi.spyOn(console, "warn");
        const pinia = createPinia();
        onTestFinished(() => disposePinia(pinia));

        const wrapper = mount(UploadMethodViewInline, {
            props: { config: { targetHistoryId: "history_id" } },
            global: { ...withPlugins(localVue, pinia), stubs: { ...localVue.stubs, GCard: true, GTip: true } },
        });

        expect(wrapper.find(".paste-links-method").exists()).toBe(true);
        const reactiveComponentWarnings = warn.mock.calls.filter((args) =>
            String(args[0]).includes("Vue received a Component that was made a reactive object"),
        );
        expect(reactiveComponentWarnings).toEqual([]);
    });
});
