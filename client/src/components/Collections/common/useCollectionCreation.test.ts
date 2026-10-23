import { createTestingPinia } from "@pinia/testing";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { AnyHistory } from "@/api";
import { useHistoryStore } from "@/stores/historyStore";

import { useCollectionCreation } from "./useCollectionCreation";
import { useCollectionCreator } from "./useCollectionCreator";

beforeEach(() => {
    setActivePinia(createTestingPinia({ createSpy: vi.fn }));
    // the only stored history is the current one
    useHistoryStore().storedHistories = { "history-1": { id: "history-1", name: "current" } as AnyHistory };
});

describe("useCollectionCreation", () => {
    it("creator creates the collection in its historyId, not the current history", () => {
        const emit = vi.fn();
        const { onCollectionCreate } = useCollectionCreator({ mode: "modal", historyId: "history-2" }, emit);
        onCollectionCreate("list", []);
        expect(emit).toHaveBeenCalledWith("on-create", expect.objectContaining({ history_id: "history-2" }));
    });

    it("falls back to the current history", () => {
        const { createPayload } = useCollectionCreation();
        expect(createPayload("reads", "list", [], false).history_id).toBe("history-1");
    });
});
