import { deferred } from "@tests/vitest/deferred";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, shallowMount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { waitOnJob } from "@/components/JobStates/wait";

import ToLink from "./ToLink.vue";

const localVue = getLocalVue();
const { server, http } = useServerMock();

const TEST_HISTORY_ID = "hist1235";
const TEST_EXPORTS_URL = `/api/histories/${TEST_HISTORY_ID}/exports`;
const TEST_JOB_ID = "test1234job";

vi.mock("@/components/JobStates/wait", () => ({
    waitOnJob: vi.fn(),
}));

afterEach(() => {
    vi.mocked(waitOnJob).mockReset();
});
enableAutoUnmount(afterEach);

describe("ToLink.vue", () => {
    async function mountWithInitialExports(exports) {
        server.use(
            http.untyped.get(TEST_EXPORTS_URL, () => {
                return HttpResponse.json(exports);
            }),
        );
        const pinia = createPinia();
        onTestFinished(() => {
            disposePinia(pinia);
            if (getActivePinia() === pinia) {
                setActivePinia(undefined);
            }
        });
        const wrapper = shallowMount(ToLink, {
            props: {
                historyId: TEST_HISTORY_ID,
            },
            global: withPlugins(localVue, pinia),
        });
        await wrapper.vm.$nextTick();
        expect(wrapper.find("loading-span-stub").exists()).toBeTruthy();
        await flushPromises();
        return wrapper;
    }

    it("should display a link if no exports ever generated", async () => {
        const wrapper = await mountWithInitialExports([]);
        const exportLink = wrapper.find(".export-link");
        expect(exportLink).toBeTruthy();
        expect(exportLink.exists()).toBe(true);
        expect(wrapper.find("loading-span-stub").exists()).toBeFalsy(); // loading span gone
    });

    it("should start polling if latest export is preparing", async () => {
        const jobCompletion = deferred();
        vi.mocked(waitOnJob).mockReturnValue(jobCompletion.promise);
        try {
            const wrapper = await mountWithInitialExports([
                {
                    preparing: true,
                    job_id: TEST_JOB_ID,
                },
            ]);
            expect(jobCompletion.resolve).toBeTruthy();
            expect(wrapper.vm.waitingOnJob).toBeTruthy();
            expect(wrapper.find("loading-span-stub").exists()).toBeTruthy();
        } finally {
            // The completed job reloads exports; return a settled history before unmount.
            server.use(http.untyped.get(TEST_EXPORTS_URL, () => HttpResponse.json([])));
            jobCompletion.resolve();
            await flushPromises();
        }
    });
});
