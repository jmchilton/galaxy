import { deferred } from "@tests/vitest/deferred";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia, getActivePinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import { createMemoryHistory, createRouter } from "vue-router";

import { useServerMock } from "@/api/client/__mocks__";
import { waitOnJob } from "@/components/JobStates/wait";

import HistoryImport from "./HistoryImport.vue";

const localVue = getLocalVue();

const TEST_JOB_ID = "job123789";
const TEST_SOURCE_URL = "http://galaxy.example/import";

vi.mock("@/components/JobStates/wait", () => ({
    waitOnJob: vi.fn(),
}));

const { server, http } = useServerMock();

describe("HistoryImport.vue", () => {
    let wrapper;

    enableAutoUnmount(afterEach);
    afterEach(async () => {
        // Settle pending URL debounce callbacks while the component is still mounted.
        await vi.runAllTimersAsync();
    });

    beforeEach(async () => {
        onTestFinished(() => {
            vi.clearAllTimers();
            vi.useRealTimers();
            vi.mocked(waitOnJob).mockReset();
        });
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        const history = createMemoryHistory();
        const router = createRouter({ history, routes: [] });
        const pinia = createPinia();
        onTestFinished(() => {
            disposePinia(pinia);
            if (getActivePinia() === pinia) {
                setActivePinia(undefined);
            }
            history.destroy();
        });
        server.use(
            http.get("/api/remote_files/plugins", ({ response }) => {
                return response(200).json([
                    {
                        id: "_ftp",
                        type: "gxftp",
                        uri_root: "gxftp://",
                        label: "FTP Directory",
                        doc: "Galaxy User's FTP Directory",
                        writable: false,
                        browsable: true,
                        supports: {
                            pagination: false,
                            search: false,
                            sorting: false,
                        },
                    },
                ]);
            }),
        );

        wrapper = mount(HistoryImport, {
            props: {},
            global: withPlugins(localVue, pinia, router),
        });
        await flushPromises();
    });

    it("should render a form with submit disabled because inputs empty", async () => {
        expect(wrapper.find(".import-button").exists()).toBeTruthy();
        expect(wrapper.get(".import-button").attributes("aria-disabled")).toBeTruthy();
        expect(wrapper.vm.importReady).toBeFalsy();
    });

    it("should allow import when URL available", async () => {
        await wrapper.setData({
            sourceURL: TEST_SOURCE_URL,
        });
        expect(wrapper.vm.importReady).toBeTruthy();
    });

    it("should require an URI if that is the import type", async () => {
        await wrapper.setData({
            sourceURL: TEST_SOURCE_URL,
            importType: "sourceRemoteFilesUri",
        });
        expect(wrapper.vm.importReady).toBeFalsy();
    });

    it("should post to create a new history and wait on job when submitted", async () => {
        await wrapper.setData({
            sourceURL: TEST_SOURCE_URL,
        });
        let formData;

        server.use(
            http.post("/api/histories", async ({ response, request }) => {
                formData = await request.formData();
                return response(200).json({ job_id: TEST_JOB_ID });
            }),
        );

        const jobCompletion = deferred();
        vi.mocked(waitOnJob).mockReturnValue(jobCompletion.promise);
        try {
            wrapper.vm.submit();
            await flushPromises();
            expect(formData.get("archive_source")).toBe(TEST_SOURCE_URL);
            expect(wrapper.vm.waitingOnJob).toBeTruthy();

            // Complete the held job before observing its finished state.
            jobCompletion.resolve({ state: "ok" });
            await flushPromises();
            expect(wrapper.vm.waitingOnJob).toBeFalsy();
            expect(wrapper.vm.complete).toBeTruthy();
        } finally {
            jobCompletion.resolve({ state: "ok" });
            await flushPromises();
        }
    });

    it("warns about shared history imports", async () => {
        const input = wrapper.get("input[type=url]");
        await input.setValue("https://usegalaxy.org/u/some_user/h/exported_history");

        await vi.advanceTimersByTimeAsync(210);

        const alert = wrapper.get(".alert");
        expect(alert.classes()).toContain("alert-warning");
        expect(alert.text()).toContain(
            "It looks like you are trying to import a published history from another galaxy instance",
        );

        // Link to the GTN
        const link = alert.get("a");
        expect(link.text()).toContain("GTN");
    });
});
