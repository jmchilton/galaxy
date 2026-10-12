import { runInTestScope } from "@tests/vitest/effectScope";
import flushPromises from "flush-promises";
import { beforeEach, expect, it, onTestFinished, vi } from "vitest";
import { ref } from "vue";

import { useToolTrainingMaterial } from "./toolTrainingMaterial";

const TRAINING_API_URL = "https://training.example.org/api/top-tools.json";

const { isConfigLoaded } = await vi.hoisted(async () => {
    const { ref } = await import("vue");
    return { isConfigLoaded: ref(true) };
});

vi.mock("./config", () => ({
    useConfig: () => ({
        config: ref({
            tool_training_recommendations: true,
            tool_training_recommendations_api_url: TRAINING_API_URL,
        }),
        isConfigLoaded,
    }),
}));

beforeEach(() => {
    onTestFinished(() => {
        isConfigLoaded.value = true;
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });
});

it("tolerates a training material request that fails to reach the server", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});

    runInTestScope(() => useToolTrainingMaterial("cat1", "Concatenate", "1.0.0"));
    await flushPromises();

    expect(warn).toHaveBeenCalled();
});

it("requests training material only once the configuration has loaded", async () => {
    isConfigLoaded.value = false;
    const fetch = vi.fn().mockResolvedValue({ ok: false });
    vi.stubGlobal("fetch", fetch);

    runInTestScope(() => useToolTrainingMaterial("cat1", "Concatenate", "1.0.0"));
    await flushPromises();
    expect(fetch).not.toHaveBeenCalled();

    isConfigLoaded.value = true;
    await flushPromises();
    expect(fetch).toHaveBeenCalledWith(TRAINING_API_URL);
});
