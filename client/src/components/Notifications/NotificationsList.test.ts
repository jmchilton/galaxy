import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { disposePinia } from "pinia";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { nextTick } from "vue";

import type { UserNotification } from "@/api/notifications";
import { useNotificationsStore } from "@/stores/notificationsStore";

import { generateNotificationsList } from "./test-utils";

import NotificationsList from "./NotificationsList.vue";

const localVue = getLocalVue(true);

enableAutoUnmount(afterEach);

async function mountNotificationsList(notifications: UserNotification[]) {
    const pinia = createTestingPinia({ createSpy: vi.fn });
    onTestFinished(() => disposePinia(pinia));

    const notificationsStore = useNotificationsStore(pinia);
    notificationsStore.notifications = notifications;

    const wrapper = mount(NotificationsList, {
        global: {
            ...withPlugins(localVue, pinia),
            stubs: { ...localVue.stubs, FontAwesomeIcon: true },
        },
    });

    await flushPromises();
    return { wrapper, notificationsStore };
}

describe("NotificationsList", () => {
    it("renders every notification and marks the six unread items", async () => {
        const { notifications, messageCount, sharedItemCount } = generateNotificationsList(10);
        const { wrapper } = await mountNotificationsList(notifications);

        expect(wrapper.findAll(".g-card")).toHaveLength(messageCount + sharedItemCount);

        const unreadNotifications = wrapper.findAll(".unread-notification");
        expect(unreadNotifications).toHaveLength(
            notifications.filter((notification) => !notification.seen_time).length,
        );
        expect(unreadNotifications).toHaveLength(6);
    });

    it("shows only unread notifications after clicking the unread filter", async () => {
        const { notifications } = generateNotificationsList(10);
        const { wrapper } = await mountNotificationsList(notifications);

        const unreadFilter = wrapper.find("#show-unread-filter");
        expect(unreadFilter.exists()).toBe(true);
        await wrapper.get("#show-unread-filter").trigger("click");

        expect(wrapper.findAll(".g-card")).toHaveLength(
            notifications.filter((notification) => !notification.seen_time).length,
        );
        expect(wrapper.findAll(".g-card")).toHaveLength(6);
    });

    it("shows the empty-state message when the notification store is cleared", async () => {
        const { notifications } = generateNotificationsList(10);
        const { wrapper, notificationsStore } = await mountNotificationsList(notifications);
        expect(wrapper.find("#no-notifications").exists()).toBe(false);

        notificationsStore.notifications = [];

        await nextTick();

        expect(wrapper.find("#no-notifications").exists()).toBe(true);
    });
});
