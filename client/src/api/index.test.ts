import { getFakeRegisteredUser } from "@tests/test-data";
import { describe, expect, it } from "vitest";

import {
    type AnonymousUser,
    type AnyHistory,
    type DCESummary,
    type HistorySummary,
    type HistorySummaryExtended,
    isRegisteredUser,
    normalizeCollectionElements,
    userOwnsHistory,
} from ".";

const REGISTERED_USER_ID = "fake-user-id";
const ANOTHER_USER_ID = "another-fake-user-id";
const ANONYMOUS_USER_ID = null;

const REGISTERED_USER = getFakeRegisteredUser({ id: REGISTERED_USER_ID });

const ANONYMOUS_USER: AnonymousUser = {
    isAnonymous: true,
    total_disk_usage: 0,
    nice_total_disk_usage: "0.0 bytes",
};

const SESSIONLESS_USER = null;

function createFakeHistory<T>(historyId: string = "fake-id", user_id?: string | null): T {
    const history: AnyHistory = {
        id: historyId,
        name: "test",
        model_class: "History",
        deleted: false,
        archived: false,
        purged: false,
        published: false,
        annotation: null,
        update_time: "2021-09-01T00:00:00.000Z",
        tags: [],
        url: `/history/${historyId}`,
        contents_active: { active: 0, deleted: 0, hidden: 0 },
        count: 0,
        size: 0,
    };
    if (user_id !== undefined) {
        (history as HistorySummaryExtended).user_id = user_id;
    }
    return history as T;
}

const HISTORY_OWNED_BY_REGISTERED_USER = createFakeHistory<HistorySummaryExtended>("1234", REGISTERED_USER_ID);
const HISTORY_OWNED_BY_ANOTHER_USER = createFakeHistory<HistorySummaryExtended>("5678", ANOTHER_USER_ID);
const HISTORY_OWNED_BY_ANONYMOUS_USER = createFakeHistory<HistorySummaryExtended>("1234", ANONYMOUS_USER_ID);
const HISTORY_SUMMARY_WITHOUT_USER_ID = createFakeHistory<HistorySummary>("1234");

describe("API Types Helpers", () => {
    describe("isRegisteredUser", () => {
        it("should return true for a registered user", () => {
            expect(isRegisteredUser(REGISTERED_USER)).toBe(true);
        });

        it("should return false for an anonymous user", () => {
            expect(isRegisteredUser(ANONYMOUS_USER)).toBe(false);
        });

        it("should return false for sessionless users", () => {
            expect(isRegisteredUser(SESSIONLESS_USER)).toBe(false);
        });
    });

    describe("isAnonymousUser", () => {
        it("should return true for an anonymous user", () => {
            expect(isRegisteredUser(ANONYMOUS_USER)).toBe(false);
        });

        it("should return false for a registered user", () => {
            expect(isRegisteredUser(REGISTERED_USER)).toBe(true);
        });

        it("should return false for sessionless users", () => {
            expect(isRegisteredUser(SESSIONLESS_USER)).toBe(false);
        });
    });

    describe("userOwnsHistory", () => {
        it("should return true for a registered user owning the history", () => {
            expect(userOwnsHistory(REGISTERED_USER, HISTORY_OWNED_BY_REGISTERED_USER)).toBe(true);
        });

        it("should return false for a registered user not owning the history", () => {
            expect(userOwnsHistory(REGISTERED_USER, HISTORY_OWNED_BY_ANOTHER_USER)).toBe(false);
        });

        it("should return true for a registered user owning a history without user_id", () => {
            expect(userOwnsHistory(REGISTERED_USER, HISTORY_SUMMARY_WITHOUT_USER_ID)).toBe(true);
        });

        it("should return true for an anonymous user owning a history with null user_id", () => {
            expect(userOwnsHistory(ANONYMOUS_USER, HISTORY_OWNED_BY_ANONYMOUS_USER)).toBe(true);
        });

        it("should return false for an anonymous user not owning a history", () => {
            expect(userOwnsHistory(ANONYMOUS_USER, HISTORY_OWNED_BY_REGISTERED_USER)).toBe(false);
        });

        it("should return false for sessionless users", () => {
            expect(userOwnsHistory(SESSIONLESS_USER, HISTORY_OWNED_BY_REGISTERED_USER)).toBe(false);
            expect(userOwnsHistory(SESSIONLESS_USER, HISTORY_SUMMARY_WITHOUT_USER_ID)).toBe(false);
            expect(userOwnsHistory(SESSIONLESS_USER, HISTORY_OWNED_BY_ANONYMOUS_USER)).toBe(false);
        });
    });

    describe("normalizeCollectionElements", () => {
        function datasetElement(objectOverrides: object = {}): DCESummary {
            return {
                id: "dce_id",
                model_class: "DatasetCollectionElement",
                element_index: 0,
                element_identifier: "forward",
                element_type: "hda",
                object: { id: "hda_id", tags: [], ...objectOverrides },
            } as unknown as DCESummary;
        }

        it("gives a dataset element's object the fields the contents API omits", () => {
            const element = datasetElement();

            normalizeCollectionElements([element]);

            // Without history_content_type, updateContentFields addresses the item as
            // /api/histories/{history_id}/contents/undefineds/{id}.
            expect(element.object).toMatchObject({
                collection_element_id: "dce_id",
                element_identifier: "forward",
                name: "forward",
                history_content_type: "dataset",
            });
        });

        it("mutates in place so each element keeps one object identity", () => {
            const element = datasetElement();
            const objectBefore = element.object;

            const [normalized] = normalizeCollectionElements([element]);

            // Selection, refs and range indices all key on this object; handing consumers
            // a derived copy would give a row two identities.
            expect(normalized).toBe(element);
            expect(element.object).toBe(objectBefore);
        });

        it("does not overwrite a name the payload already carries", () => {
            const element = datasetElement({ name: "real dataset name" });

            normalizeCollectionElements([element]);

            expect(element.object).toMatchObject({ name: "real dataset name" });
        });

        it("leaves sub-collection elements alone", () => {
            const element = {
                id: "dce_id",
                model_class: "DatasetCollectionElement",
                element_index: 0,
                element_identifier: "nested",
                element_type: "dataset_collection",
                object: { id: "dc_id", collection_type: "paired" },
            } as unknown as DCESummary;

            normalizeCollectionElements([element]);

            // Sub-collections become SubCollection entries on drill-down instead.
            expect(element.object).not.toHaveProperty("history_content_type");
            expect(element.object).not.toHaveProperty("name");
        });

        it("tolerates an element with no object", () => {
            const element = datasetElement();
            (element as unknown as { object: unknown }).object = null;

            expect(() => normalizeCollectionElements([element])).not.toThrow();
        });
    });
});
