import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { defineComponent } from "vue";

import { Toast } from "@/composables/__mocks__/toast";

import { useDataLoading } from "./util";

vi.mock("@/composables/toast");

beforeEach(() => {
    Toast.error.mockClear();
});
afterEach(() => {
    Toast.error.mockClear();
});
enableAutoUnmount(afterEach);

it("reports a failed load and stops loading", async () => {
    const { isLoading, loadDataOnMount } = useDataLoading();
    mount(
        defineComponent({
            setup() {
                loadDataOnMount(async () => {
                    throw new TypeError("Failed to fetch");
                });
                return {};
            },
            template: "<div />",
        }),
    );
    await flushPromises();
    expect(isLoading.value).toBe(false);
    expect(Toast.error).toHaveBeenCalledWith("Failed to fetch", "An error occurred while loading storage data.");
});
