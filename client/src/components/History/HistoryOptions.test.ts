import { getFakeAnonymousUser, getFakeHistorySummary, getFakeRegisteredUser } from "@tests/test-data";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import { BFormCheckbox } from "bootstrap-vue";
import flushPromises from "flush-promises";
import { createPinia, disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import type { HistorySummary, RegisteredUser } from "@/api";
import { useHistoryStore } from "@/stores/historyStore";
import { useUserStore } from "@/stores/userStore";

import HistoryOptions from "./HistoryOptions.vue";
import GDropdownItem from "@/components/BaseComponents/GDropdownItem.vue";
import GModal from "@/components/BaseComponents/GModal.vue";

const localVue = getLocalVue();

// all options
const expectedOptions = [
    "Show Histories Side-by-Side",
    "Resume Paused Jobs",
    "Copy History",
    "Copy Datasets",
    "Delete History",
    "Export Tool References",
    "Export History to File",
    "Archive History",
    "Extract Workflow",
    "Show Invocations",
    "Show History Graph",
    "Show History Notebooks",
    "Share & Manage Access",
];

// options enabled for logged-out users
const anonymousOptions = [
    "Resume Paused Jobs",
    "Delete History",
    "Export Tool References",
    "Export History to File",
    "Show History Graph",
];

// options disabled for logged-out users
const anonymousDisabledOptions = expectedOptions.filter((option) => !anonymousOptions.includes(option));

const activeHistory = getFakeHistorySummary({ id: "history_a", name: "Active History" });
const deletedHistory = getFakeHistorySummary({ id: "history_b", name: "Deleted History", deleted: true });

// options still shown for a history owned by someone else
const unownedHistoryOptions = [
    "Show Histories Side-by-Side",
    "Copy History",
    "Export Tool References",
    "Export History to File",
    "Extract Workflow",
    "Show Invocations",
    "Show History Graph",
    "Show History Notebooks",
];

async function createWrapper(
    props: { history: Partial<HistorySummary> & { user_id?: string | null } },
    userData?: RegisteredUser,
) {
    const pinia = createPinia();
    onTestFinished(() => disposePinia(pinia));

    const historyUserId = "user_id" in props.history ? (props.history.user_id ?? null) : (userData?.id ?? null);

    const history: HistorySummary & { user_id: string | null } = {
        ...getFakeHistorySummary(props.history),
        user_id: historyUserId,
    };

    const wrapper = shallowMount(HistoryOptions, {
        props: { history },
        global: withPlugins(localVue, pinia),
    });

    const userStore = useUserStore(pinia);
    userStore.currentUser = userData ?? getFakeAnonymousUser();

    const historyStore = useHistoryStore(pinia);
    vi.spyOn(historyStore, "currentHistoryId", "get").mockReturnValue("current_history_id");
    vi.spyOn(historyStore, "deleteHistory").mockImplementation(async () => {});

    await flushPromises();
    return { wrapper, historyStore };
}

afterEach(() => {
    vi.restoreAllMocks();
});
enableAutoUnmount(afterEach);

describe("History Navigation", () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it("presents all options to logged-in users", async () => {
        const { wrapper } = await createWrapper(
            {
                history: { id: "current_history_id" },
            },
            getFakeRegisteredUser(),
        );

        const optionElements = wrapper.findAllComponents(GDropdownItem);
        const optionTexts = optionElements.map((el) => el.text());

        expect(optionTexts).toStrictEqual(expectedOptions);
    });

    it("disables options for anonymous users", async () => {
        const { wrapper } = await createWrapper({
            history: { id: "current_history_id" },
        });

        const allItems = wrapper.findAllComponents(GDropdownItem);
        const enabledOptionTexts = allItems.filter((el) => !el.props("disabled")).map((el) => el.text());
        expect(enabledOptionTexts).toStrictEqual(anonymousOptions);

        const disabledOptionTexts = allItems.filter((el) => el.props("disabled")).map((el) => el.text());
        expect(disabledOptionTexts).toStrictEqual(anonymousDisabledOptions);
    });

    it("prompts anonymous users to log in", async () => {
        const { wrapper } = await createWrapper({
            history: { id: "current_history_id" },
        });

        const allItems = wrapper.findAllComponents(GDropdownItem);
        const disabledItems = allItems.filter((el) => el.props("disabled"));

        disabledItems.forEach((option) => {
            expect((option.props("title") as string).toLowerCase()).toContain("log in");
        });
    });

    it("hides owner-only options for a history not owned by the current user", async () => {
        const { wrapper } = await createWrapper(
            {
                history: { ...activeHistory, user_id: "someone_else" },
            },
            getFakeRegisteredUser({ id: "fake_user_id" }),
        );

        const optionElements = wrapper.findAllComponents(GDropdownItem);
        const optionTexts = optionElements.map((el) => el.text());

        expect(optionTexts).toStrictEqual(unownedHistoryOptions);
    });

    it("shows 'Delete History' for an active history", async () => {
        const { wrapper } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());
        expect(wrapper.text()).toContain("Delete History");
        expect(wrapper.text()).not.toContain("Permanently Delete History");
    });

    it("shows 'Permanently Delete History' for a deleted (not purged) history", async () => {
        const { wrapper } = await createWrapper({ history: deletedHistory }, getFakeRegisteredUser());
        expect(wrapper.text()).toContain("Permanently Delete History");
    });

    it("delete modal has correct title and ok-text for an active history", async () => {
        const { wrapper } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());
        const modal = wrapper.getComponent(GModal);
        expect(modal.props("title")).toBe("Delete History?");
        expect(modal.props("okText")).toBe("Delete");
    });

    it("delete modal has correct title and ok-text for a deleted (not purged) history", async () => {
        const { wrapper } = await createWrapper({ history: deletedHistory }, getFakeRegisteredUser());
        const modal = wrapper.getComponent(GModal);
        expect(modal.props("title")).toBe("Permanently Delete History?");
        expect(modal.props("okText")).toBe("Delete Permanently");
    });

    it("purge checkbox is not disabled for an active history", async () => {
        const { wrapper } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());
        expect(wrapper.get('[data-description="delete history checkbox"]').attributes("disabled")).toBeUndefined();
    });

    it("purge checkbox is disabled for an already-deleted history", async () => {
        const { wrapper } = await createWrapper({ history: deletedHistory }, getFakeRegisteredUser());
        expect(wrapper.get('[data-description="delete history checkbox"]').attributes("disabled")).toBeDefined();
    });

    it("calls deleteHistory with purge=false when checkbox is unchecked", async () => {
        const { wrapper, historyStore } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());
        wrapper.getComponent(GModal).vm.$emit("ok");
        await flushPromises();
        expect(historyStore.deleteHistory).toHaveBeenCalledWith("history_a", false);
    });

    it("calls deleteHistory with purge=true when purge checkbox is manually checked", async () => {
        const { wrapper, historyStore } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());
        // BFormCheckbox is stubbed under shallowMount, so there's no real
        // checkbox input to interact with -- drive it through its stub instead.
        wrapper.getComponent(BFormCheckbox).vm.$emit("input", true);
        await flushPromises();
        wrapper.getComponent(GModal).vm.$emit("ok");
        await flushPromises();
        expect(historyStore.deleteHistory).toHaveBeenCalledWith("history_a", true);
    });

    it("auto-sets purge=true when history changes to a deleted one while modal is open", async () => {
        // The watch fires on history.id change — covers the case where the modal is already open
        // and the history switches to a deleted one (e.g. another tab deletes it).
        const { wrapper, historyStore } = await createWrapper({ history: activeHistory }, getFakeRegisteredUser());

        expect(wrapper.getComponent(GModal).text()).toContain(activeHistory.name);

        await wrapper.setProps({ history: deletedHistory });

        expect(wrapper.getComponent(GModal).text()).toContain(deletedHistory.name);

        await flushPromises();
        wrapper.getComponent(GModal).vm.$emit("ok");

        await flushPromises();
        expect(historyStore.deleteHistory).toHaveBeenCalledWith("history_b", true);
    });
});
