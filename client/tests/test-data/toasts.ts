import { GToast } from "@galaxyproject/galaxy-ui";
import type { Decorator } from "@storybook/vue3-vite";
import { h } from "vue";

import { useToast } from "@/composables/toast";

/** Name of the region `withToasts` shows toasts in; plays find them within it. */
export const NOTIFICATIONS = "Notifications";

/**
 * The app shell's toast stack beside the story, in a region named `NOTIFICATIONS` so a toast
 * (role `alert`) isn't confused with the story's own alerts. Starts each story with no toasts.
 */
export const withToasts: Decorator = (story) => ({
    setup() {
        useToast().clearToasts();
    },
    render: () => h("div", [h(story()), h("section", { "aria-label": NOTIFICATIONS }, [h(GToast)])]),
});
