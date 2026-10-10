import type { Decorator } from "@storybook/vue3-vite";
import { h } from "vue";

import type { AnyHistory } from "@/api";
import { seedCurrentHistory } from "@/stores/testUtils";

/** Puts a copy of `history` in the history store as the user's current history, as the app does after loading it. */
export function withCurrentHistory(history: AnyHistory): Decorator {
    return (story) => ({
        setup() {
            seedCurrentHistory({ ...history });
        },
        render: () => h(story()),
    });
}
