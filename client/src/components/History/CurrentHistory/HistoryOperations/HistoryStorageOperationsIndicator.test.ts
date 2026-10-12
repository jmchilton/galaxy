import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import { disposePinia } from "pinia";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";

import HistoryStorageOperationsIndicator from "./HistoryStorageOperationsIndicator.vue";
import GPopover from "@/components/BaseComponents/GPopover.vue";

vi.mock("@/composables/useStorageRunWatcher", () => ({
    useStorageHistoryRunsWatcher: () => ({ startPolling: vi.fn(), stopPolling: vi.fn() }),
}));

describe("HistoryStorageOperationsIndicator", () => {
    enableAutoUnmount(afterEach);
    it("lets keyboard users reach the link in the storage helper popover", () => {
        const pinia = createTestingPinia({ createSpy: vi.fn });
        onTestFinished(() => disposePinia(pinia));
        const wrapper = mount(HistoryStorageOperationsIndicator, {
            props: { historyId: "history_id", showSelection: false, activeStorageRunCount: 1 },
            global: withPlugins(getLocalVue(), pinia),
        });

        const popover = wrapper.getComponent(GPopover);
        expect(popover.props("interactive")).toBe(true);
        expect(popover.props("ariaLabel")).toBe("Background storage operations");
        expect(wrapper.get("#history-storage-operations-history_id").attributes("aria-label")).toBe(
            "Background operations are running",
        );

        wrapper.unmount();
    });
});
