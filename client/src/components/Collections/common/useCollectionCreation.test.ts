import { createTestingPinia } from "@pinia/testing";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCollectionCreation } from "./useCollectionCreation";

beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn }));
});

describe("useCollectionCreation", () => {
    it("creates the collection in the given history", () => {
        const { createPayload } = useCollectionCreation(() => "history-2");
        expect(createPayload("reads", "list", [], false).history_id).toBe("history-2");
    });

    it("falls back to the current history", () => {
        const { createPayload } = useCollectionCreation();
        expect(createPayload("reads", "list", [], false).history_id).toBe("current");
    });
});
