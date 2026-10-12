import { deferred } from "@tests/vitest/deferred";
import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { setupMockConfig } from "@tests/vitest/mockConfig";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { Toast } from "@/composables/toast";

import StsDownloadButton from "./StsDownloadButton.vue";

const localVue = getLocalVue();
const { server, http } = useServerMock();

const NO_TASKS_CONFIG = {
    enable_celery_tasks: false,
};
const TASKS_CONFIG = {
    enable_celery_tasks: true,
};
const FALLBACK_URL = "http://cow.com/direct_download";
const DOWNLOAD_ENDPOINT = "http://cow.com/prepare_download";
const STORAGE_REQUEST_ID = "moocow1235";
const POLL_DELAY = 200;

async function mountDownloadButton(config) {
    setupMockConfig(config);

    const pinia = createPinia();
    onTestFinished(() => disposePinia(pinia));
    const wrapper = mount(StsDownloadButton, {
        props: {
            title: "my title",
            fallbackUrl: FALLBACK_URL,
            downloadEndpoint: DOWNLOAD_ENDPOINT,
        },
        global: withPlugins(localVue, pinia),
    });
    await flushPromises();
    return wrapper;
}

describe("StsDownloadButton", () => {
    beforeEach(() => {
        vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    });
    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
        vi.restoreAllMocks();
    });
    enableAutoUnmount(afterEach);

    it("should fallback to a URL if tasks not enabled", async () => {
        const windowSpy = vi.spyOn(window, "open");
        windowSpy.mockImplementation(() => {});
        const wrapper = await mountDownloadButton(NO_TASKS_CONFIG);
        await wrapper.get("button").trigger("click");
        await flushPromises();
        expect(window.open).toHaveBeenCalled();
    });

    it("should poll until ready", async () => {
        server.use(
            http.untyped.post(DOWNLOAD_ENDPOINT, () => {
                return HttpResponse.json({ storage_request_id: STORAGE_REQUEST_ID });
            }),
            http.untyped.get(`api/short_term_storage/${STORAGE_REQUEST_ID}/ready`, () => {
                return HttpResponse.json(true);
            }),
        );
        const wrapper = await mountDownloadButton(TASKS_CONFIG);

        await wrapper.get("button").trigger("click");
        await flushPromises();
        expect(window.location).toBeAt(`api/short_term_storage/${STORAGE_REQUEST_ID}`);
    });

    it("should be in a waiting state while polling", async () => {
        server.use(
            http.untyped.post(DOWNLOAD_ENDPOINT, () => {
                return HttpResponse.json({ storage_request_id: STORAGE_REQUEST_ID });
            }),
            http.untyped.get(`api/short_term_storage/${STORAGE_REQUEST_ID}/ready`, () => {
                return HttpResponse.json(false);
            }),
        );
        const wrapper = await mountDownloadButton(TASKS_CONFIG);

        expect(wrapper.find(".fa-spinner").exists()).toBeFalsy();
        await wrapper.get("button").trigger("click");
        await flushPromises();
        expect(wrapper.find(".fa-spinner").exists()).toBeTruthy();
    });

    it("stops waiting and reports a poll failure without navigating", async () => {
        let readyRequests = 0;
        const errorSpy = vi.spyOn(Toast, "error").mockImplementation(() => {});
        const assignSpy = vi.spyOn(window.location, "assign");
        server.use(
            http.untyped.post(DOWNLOAD_ENDPOINT, () => {
                return HttpResponse.json({ storage_request_id: STORAGE_REQUEST_ID });
            }),
            http.untyped.get(`api/short_term_storage/${STORAGE_REQUEST_ID}/ready`, () => {
                readyRequests += 1;
                return readyRequests === 1
                    ? HttpResponse.json(false)
                    : HttpResponse.json({ err_msg: "Storage is unavailable", err_code: 500 }, { status: 500 });
            }),
        );
        const wrapper = await mountDownloadButton(TASKS_CONFIG);

        await wrapper.get("button").trigger("click");
        await flushPromises();
        expect(wrapper.find(".fa-spinner").exists()).toBeTruthy();

        vi.advanceTimersByTime(POLL_DELAY);
        await flushPromises();

        expect(errorSpy).toHaveBeenCalledWith("Failed to generate download: Storage is unavailable");
        expect(wrapper.find(".fa-spinner").exists()).toBeFalsy();
        expect(assignSpy).not.toHaveBeenCalled();
    });

    it.each([
        ["ready", true],
        ["not ready", false],
    ])("should not poll or navigate when a %s response arrives after unmount", async (_label, ready) => {
        const storageRequestId = `in-flight-poll-${ready}`;
        let readyRequests = 0;
        const pendingPoll = deferred();
        server.use(
            http.untyped.post(DOWNLOAD_ENDPOINT, () => {
                return HttpResponse.json({ storage_request_id: storageRequestId });
            }),
            http.untyped.get(`api/short_term_storage/${storageRequestId}/ready`, async () => {
                readyRequests += 1;
                if (readyRequests > 1) {
                    await pendingPoll.promise;
                    return HttpResponse.json(ready);
                }
                return HttpResponse.json(false);
            }),
        );
        const wrapper = await mountDownloadButton(TASKS_CONFIG);
        const assignSpy = vi.spyOn(window.location, "assign");
        try {
            await wrapper.get("button").trigger("click");
            await flushPromises();
            expect(readyRequests).toBe(1);

            vi.advanceTimersByTime(POLL_DELAY);
            await vi.waitFor(() => expect(readyRequests).toBe(2));

            wrapper.unmount();
            pendingPoll.resolve();
            await flushPromises();
            vi.advanceTimersByTime(POLL_DELAY * 10);
            await flushPromises();
            expect(readyRequests).toBe(2);
            expect(assignSpy).not.toHaveBeenCalled();
        } finally {
            if (wrapper.exists()) {
                wrapper.unmount();
            }
            pendingPoll.resolve();
            await flushPromises();
        }
    });

    it("should not start polling when the prepare request resolves after unmount", async () => {
        const storageRequestId = "in-flight-prepare";
        let readyRequests = 0;
        const pendingPost = deferred();
        server.use(
            http.untyped.post(DOWNLOAD_ENDPOINT, async () => {
                await pendingPost.promise;
                return HttpResponse.json({ storage_request_id: storageRequestId });
            }),
            http.untyped.get(`api/short_term_storage/${storageRequestId}/ready`, () => {
                readyRequests += 1;
                return HttpResponse.json(false);
            }),
        );
        const wrapper = await mountDownloadButton(TASKS_CONFIG);

        try {
            await wrapper.get("button").trigger("click");
            wrapper.unmount();
            pendingPost.resolve();
            await flushPromises();
            vi.advanceTimersByTime(POLL_DELAY * 2);
            await flushPromises();
            expect(readyRequests).toBe(0);
        } finally {
            if (wrapper.exists()) {
                wrapper.unmount();
            }
            pendingPost.resolve();
            await flushPromises();
        }
    });
});
