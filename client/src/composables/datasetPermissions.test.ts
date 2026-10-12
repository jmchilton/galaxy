import { deferred } from "@tests/vitest/deferred";
import { AxiosHeaders, type AxiosResponse } from "axios";
import flushPromises from "flush-promises";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Toast } from "@/composables/toast";

import { useCallbacks } from "./datasetPermissions";

vi.mock("@/composables/toast", () => {
    const toast = { error: vi.fn(), success: vi.fn() };
    return { Toast: toast, useToast: () => toast };
});

describe("dataset permissions callbacks", () => {
    afterEach(() => vi.clearAllMocks());

    it("starts loading immediately and clears the loading state after permissions arrive", async () => {
        const loadPermissions = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

        const { loading, loadError } = useCallbacks(loadPermissions);
        expect(loading.value).toBe(true);
        await vi.waitFor(() => expect(loading.value).toBe(false));
        expect(loadError.value).toBe("");
    });

    it("stores a denied initial request as a load error without showing an error toast", async () => {
        const error = new Error("Request failed with status code 403");
        const loadPermissions = vi.fn<() => Promise<void>>().mockRejectedValue(error);

        const { loading, loadError } = useCallbacks(loadPermissions);
        await vi.waitFor(() => expect(loading.value).toBe(false));
        expect(loadError.value).toBe(error.message);
        expect(Toast.error).not.toHaveBeenCalled();
        expect(loadPermissions).toHaveBeenCalledTimes(1);
    });

    it("confirms the save and stores a denied permissions reload as a load error", async () => {
        const error = new Error("Request failed with status code 403");
        const reloadResponse = deferred<void>();
        const loadPermissions = vi
            .fn<() => Promise<void>>()
            .mockResolvedValueOnce(undefined)
            .mockImplementationOnce(async () => {
                await reloadResponse.promise;
                throw error;
            });
        const savedPermissionsResponse = {
            data: { message: "Saved" },
            status: 200,
            statusText: "OK",
            headers: new AxiosHeaders(),
            config: { headers: new AxiosHeaders() },
        } satisfies AxiosResponse<{ message: string }>;
        const { loading, loadError, onSuccess } = useCallbacks(loadPermissions);
        await vi.waitFor(() => expect(loading.value).toBe(false));
        expect(loadError.value).toBe("");

        let saveCallbackCompleted = false;
        const saveCallback = onSuccess(savedPermissionsResponse).then(() => {
            saveCallbackCompleted = true;
        });
        try {
            await flushPromises();
            expect(loadPermissions).toHaveBeenCalledTimes(2);
            expect(saveCallbackCompleted).toBe(false);
        } finally {
            // Settle the denied request even when a pending-state assertion fails.
            reloadResponse.resolve();
            await saveCallback;
        }

        expect(Toast.success).toHaveBeenCalledWith("Saved");
        expect(loadPermissions).toHaveBeenCalledTimes(2);
        expect(loadError.value).toBe(error.message);
        expect(Toast.error).not.toHaveBeenCalled();
    });
});
