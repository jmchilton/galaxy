import { getFakeObjectStoreInstance } from "@tests/test-data/objectStores";
import { runInTestScope } from "@tests/vitest/effectScope";
import { describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import { useServerMock } from "@/api/client/__mocks__";
import type { PluginStatus } from "@/api/configTemplates";

import { OK_PLUGIN_STATUS, STANDARD_OBJECT_STORE_TEMPLATE } from "./test_fixtures";
import { useConfigurationTemplateEdit, useConfigurationTemplateUpgrade } from "./useConfigurationTesting";

const { server, http } = useServerMock();

const INSTANCE = getFakeObjectStoreInstance({
    name: "moo",
    template_id: "moo",
    template_version: 1,
    variables: { oldvar: "my old value" },
    secrets: ["oldsecret"],
    uuid: "112f889f-72d7-4619-a8e8-510a8c685aa7",
});

const FAILED_CONNECTION_STATUS: PluginStatus = {
    ...OK_PLUGIN_STATUS,
    connection: { state: "not_ok", message: "could not connect" },
};

function mockFailedTestAndTrackUpdates({ requestFails = false } = {}) {
    const updateRequests = vi.fn();
    server.use(
        http.post("/api/object_store_instances/{uuid}/test", ({ response }) => {
            if (requestFails) {
                return response("5XX").json({ err_code: 500, err_msg: "test request failed" }, { status: 500 });
            }
            return response(200).json(FAILED_CONNECTION_STATUS);
        }),
        http.put("/api/object_store_instances/{uuid}", ({ response }) => {
            updateRequests();
            return response(200).json(INSTANCE);
        }),
    );
    return updateRequests;
}

const useRouting = () => ({ goToIndex: vi.fn<(query: Record<"message", string>) => Promise<void>>() });

describe("useConfigurationTemplateEdit", () => {
    it("stops and offers to force the update when the configuration test fails", async () => {
        const updateRequests = mockFailedTestAndTrackUpdates();
        const { onSubmit, error, showForceActionButton } = runInTestScope(() =>
            useConfigurationTemplateEdit(
                "storage location",
                ref(INSTANCE),
                ref(STANDARD_OBJECT_STORE_TEMPLATE),
                "/api/object_store_instances/{uuid}/test",
                "/api/object_store_instances/{uuid}",
                useRouting,
            ),
        );

        await onSubmit({});

        expect(error.value).toBe("could not connect");
        expect(showForceActionButton.value).toBe(true);
        expect(updateRequests).not.toHaveBeenCalled();
    });

    it("stops and offers to force the update when the test request itself fails", async () => {
        const updateRequests = mockFailedTestAndTrackUpdates({ requestFails: true });
        const { onSubmit, error, showForceActionButton } = runInTestScope(() =>
            useConfigurationTemplateEdit(
                "storage location",
                ref(INSTANCE),
                ref(STANDARD_OBJECT_STORE_TEMPLATE),
                "/api/object_store_instances/{uuid}/test",
                "/api/object_store_instances/{uuid}",
                useRouting,
            ),
        );

        await onSubmit({});

        expect(error.value).toBe("test request failed");
        expect(showForceActionButton.value).toBe(true);
        expect(updateRequests).not.toHaveBeenCalled();
    });
});

describe("useConfigurationTemplateUpgrade", () => {
    it("stops and offers to force the upgrade when the configuration test fails", async () => {
        const updateRequests = mockFailedTestAndTrackUpdates();
        const { onSubmit, error, showForceActionButton } = runInTestScope(() =>
            useConfigurationTemplateUpgrade(
                "storage location",
                ref(INSTANCE),
                ref(STANDARD_OBJECT_STORE_TEMPLATE),
                "/api/object_store_instances/{uuid}/test",
                "/api/object_store_instances/{uuid}",
                useRouting,
            ),
        );

        await onSubmit({});

        expect(error.value).toBe("could not connect");
        expect(showForceActionButton.value).toBe(true);
        expect(updateRequests).not.toHaveBeenCalled();
    });
});
