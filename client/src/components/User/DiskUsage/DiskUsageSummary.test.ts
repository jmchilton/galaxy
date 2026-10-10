import { getLocalVue, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, disposePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { toAnyUser } from "@/api";
import { apiFixture } from "@/api/__fixtures__";
import { HttpResponse, useServerMock } from "@/api/client/__mocks__";
import { useUserStore } from "@/stores/userStore";

import DiskUsageSummary from "./DiskUsageSummary.vue";

const localVue = getLocalVue();

const { server, http } = useServerMock();

const quotaUsageClassSelector = ".quota-usage";
const basicDiskUsageSummaryId = "#basic-disk-usage-summary";

// A user with one 6 byte dataset under a 100 MB default quota.
const userWithQuota = apiFixture("/api/users/{user_id}", "get", "under_quota");
const quotaUsages = apiFixture("/api/users/{user_id}/usage", "get", "under_quota");

const FAKE_TASK_ID = "fakeTaskId";

async function mountDiskUsageSummary(enableQuotas: boolean, usages = quotaUsages) {
    server.use(
        http.get("/api/configuration", ({ response }) => {
            return response.untyped(HttpResponse.json({ enable_quotas: enableQuotas }));
        }),
        http.get("/api/users/{user_id}", ({ response }) => {
            return response(200).json(userWithQuota);
        }),
        http.get("/api/users/{user_id}/usage", ({ response }) => {
            return response(200).json(usages);
        }),
    );

    const pinia = createPinia();
    onTestFinished(() => disposePinia(pinia));
    const wrapper = mount(DiskUsageSummary, {
        global: withPlugins(localVue, pinia),
    });
    const userStore = useUserStore(pinia);
    userStore.currentUser = toAnyUser(userWithQuota);
    await flushPromises();
    return wrapper;
}

describe("DiskUsageSummary", () => {
    beforeEach(() => {
        vi.useFakeTimers();
    });
    afterEach(() => {
        vi.clearAllTimers();
        vi.useRealTimers();
    });
    enableAutoUnmount(afterEach);

    it("shows basic disk usage when quotas are disabled", async () => {
        const wrapper = await mountDiskUsageSummary(false);
        expect(wrapper.find(basicDiskUsageSummaryId).exists()).toBe(true);
        const quotaUsages = wrapper.findAll(quotaUsageClassSelector);
        expect(quotaUsages.length).toBe(0);
    });

    it("shows quota usage when quotas are enabled", async () => {
        const wrapper = await mountDiskUsageSummary(true);
        expect(wrapper.find(basicDiskUsageSummaryId).exists()).toBe(false);
        const quotaUsages = wrapper.findAll(quotaUsageClassSelector);
        expect(quotaUsages.length).toBe(1);
    });

    it("should display the correct quota usage", async () => {
        const enableQuotasInConfig = true;
        const wrapper = await mountDiskUsageSummary(enableQuotasInConfig);
        const quotaUsage = wrapper.find(quotaUsageClassSelector);
        expect(quotaUsage.text()).toContain("6 b of 100 MB used");
    });

    it("should label each storage source with its own quota", async () => {
        // The default source plus an "ebs" source with a 10 MB quota and an unlimited "s3" source.
        const usagesPerSource = apiFixture("/api/users/{user_id}/usage", "get", "per_quota_source");
        const wrapper = await mountDiskUsageSummary(true, usagesPerSource);
        expect(wrapper.findAll(".storage-source-label").map((label) => label.text())).toEqual(["ebs", "s3"]);
        expect(wrapper.findAll(quotaUsageClassSelector).map((usage) => usage.text())).toEqual([
            "6 b of 100 MB used",
            "0 b of 10 MB used",
            "0 b used",
        ]);
    });

    it("should refresh the quota usage when the user clicks the refresh button", async () => {
        const enableQuotasInConfig = true;
        const wrapper = await mountDiskUsageSummary(enableQuotasInConfig);
        const quotaUsage = wrapper.find(quotaUsageClassSelector);
        expect(quotaUsage.text()).toContain("6 b of 100 MB used");
        // The same user after uploading a second, 12 byte dataset.
        const grownQuotaUsages = apiFixture("/api/users/{user_id}/usage", "get", "after_second_upload");
        server.use(
            http.get("/api/users/{user_id}/usage", ({ response }) => {
                return response(200).json(grownQuotaUsages);
            }),
            http.put("/api/users/current/recalculate_disk_usage", ({ response }) => {
                return response(200).json({ id: FAKE_TASK_ID, ignored: false });
            }),
            http.get("/api/tasks/{task_id}/state", ({ response }) => {
                return response(200).json("PENDING");
            }),
        );
        const refreshButton = wrapper.get("#refresh-disk-usage");
        await refreshButton.trigger("click");
        await flushPromises();
        expect(wrapper.find(".refreshing-alert").exists()).toBe(true);

        server.use(
            http.get("/api/tasks/{task_id}/state", ({ response }) => {
                return response(200).json("SUCCESS");
            }),
        );
        vi.runAllTimers();
        await flushPromises();

        expect(wrapper.find(".refreshing-alert").exists()).toBe(false);
        expect(quotaUsage.text()).toContain("18 b of 100 MB used");
    });
});
