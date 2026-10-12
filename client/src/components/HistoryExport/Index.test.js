import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia } from "pinia";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { useFileSources } from "@/composables/fileSources";

import Index from "./Index.vue";

vi.mock("@/composables/fileSources");

const localVue = getLocalVue();
const fileSourcesMock = vi.mocked(useFileSources);
const originalFileSourcesImplementation = fileSourcesMock.getMockImplementation();

afterEach(() => {
    fileSourcesMock.mockReset();
    if (originalFileSourcesImplementation) {
        fileSourcesMock.mockImplementation(originalFileSourcesImplementation);
    }
});
enableAutoUnmount(afterEach);

describe("HistoryExport", () => {
    it("shows export tabs when writable file sources are available", async () => {
        fileSourcesMock.mockReturnValue({ isLoading: false, hasWritable: true });
        const pinia = createTestingPinia({ createSpy: vi.fn });
        onTestFinished(() => disposePinia(pinia));
        const wrapper = shallowMount(Index, {
            props: {
                historyId: "test_id",
            },
            global: withPlugins(localVue, pinia),
        });
        await flushPromises();

        const tabs = wrapper.findComponent(".history-export-tabs");
        expect(tabs.exists()).toBeTruthy();
    });
});
