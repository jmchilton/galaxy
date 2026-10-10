import type { AnonymousUser, HistorySummary, HistorySummaryExtended, RegisteredUser } from "@/api";
import { apiFixture } from "@/api/__fixtures__";

export function getFakeRegisteredUser(data: Partial<RegisteredUser> = {}): RegisteredUser {
    return {
        id: "fake_user_id",
        email: "fake_user_email",
        isAnonymous: false,
        username: "fake_username",
        total_disk_usage: 0,
        nice_total_disk_usage: "0.0 bytes",
        deleted: false,
        purged: false,
        is_admin: false,
        preferences: {},
        quota: "default",
        ...data,
    };
}

/** A visitor with a session but no account: a non-null user without an email. */
export function getFakeAnonymousUser(data: Partial<AnonymousUser> = {}): AnonymousUser {
    return {
        isAnonymous: true,
        total_disk_usage: 0,
        nice_total_disk_usage: "0.0 bytes",
        ...data,
    };
}

export function getFakeHistorySummary(data: Partial<HistorySummary> = {}): HistorySummary {
    return {
        id: "fake_history_id",
        name: "Unnamed history",
        model_class: "History",
        annotation: null,
        archived: false,
        count: 0,
        deleted: false,
        purged: false,
        published: false,
        tags: [],
        update_time: "2026-01-01T00:00:00",
        url: "/api/histories/fake_history_id",
        ...data,
    };
}

/** A history recorded from Galaxy: one 6 byte dataset, as the history store requests it. */
export function getFakeHistorySummaryExtended(data: Partial<HistorySummaryExtended> = {}): HistorySummaryExtended {
    // The store requests view=summary with these extra keys, so the response is HistorySummaryExtended.
    const history = apiFixture("/api/histories/{history_id}", "get", "summary_extended") as HistorySummaryExtended;
    return { ...history, ...data };
}
