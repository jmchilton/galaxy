import { describe, expect, it } from "vitest";

import type { ToolFormBatchInputCount, ToolFormJobExpansion } from "@/api/tools";
import type { FormInputNode } from "@/components/Form/composables/useFormState";

import { jobCountNotices, runBlockedReason } from "./jobCount";

const inputs = [
    { name: "reads", type: "data", label: "Input reads" },
    {
        name: "cond",
        type: "conditional",
        test_param: { name: "mode", type: "select", value: "paired" },
        cases: [
            {
                value: "paired",
                inputs: [{ name: "reverse", type: "data", label: "Reverse reads" }],
            },
        ],
    },
    { name: "extra", type: "data_collection", label: "Extra" },
    {
        name: "advanced",
        type: "section",
        title: "Advanced",
        inputs: [{ name: "mask", type: "data", label: "Select" }],
    },
    {
        name: "queries",
        type: "repeat",
        title: "Query",
        cache: [
            [{ name: "input2", type: "data", label: "Select" }],
            [{ name: "input2", type: "data", label: "Select" }],
        ],
    },
] as unknown as FormInputNode[];

function batched(name: string, count: number, linked = true): ToolFormBatchInputCount {
    return { name, count, linked };
}

function expansion(overrides: Partial<ToolFormJobExpansion>): ToolFormJobExpansion {
    return { job_count: null, reason: null, inputs: [], ...overrides };
}

describe("jobCountNotices", () => {
    it("says nothing without an expansion, for a single job, or an unknown count", () => {
        expect(jobCountNotices(undefined, inputs)).toEqual([]);
        expect(jobCountNotices(expansion({ job_count: 1, inputs: [batched("reads", 1)] }), inputs)).toEqual([]);
        expect(jobCountNotices(expansion({ reason: "unknown", inputs: [batched("reads", 3)] }), inputs)).toEqual([]);
    });

    it("counts jobs without a breakdown for a single batch input", () => {
        const notices = jobCountNotices(expansion({ job_count: 12, inputs: [batched("reads", 12)] }), inputs);
        expect(notices).toEqual([
            { variant: "info", kind: "count", text: "This will run 12 jobs.", detail: undefined },
        ]);
    });

    it("breaks down matched and multiplied inputs by label", () => {
        const notices = jobCountNotices(
            expansion({
                job_count: 6,
                inputs: [batched("reads", 3), batched("cond|reverse", 3), batched("extra", 2, false)],
            }),
            inputs,
        );
        expect(notices[0]!.detail).toBe("Batch inputs: Input reads, Reverse reads (3 each) × Extra (2)");
    });

    it("warns that an empty batch input runs no jobs", () => {
        const notices = jobCountNotices(expansion({ job_count: 0, inputs: [batched("extra", 0)] }), inputs);
        expect(notices).toEqual([
            { variant: "warning", kind: "empty", text: "No jobs will run because a batch input is empty: Extra." },
        ]);
    });

    it("names mismatched sizes by label", () => {
        const notices = jobCountNotices(
            expansion({ reason: "batch_mismatch", inputs: [batched("reads", 2), batched("cond|reverse", 3)] }),
            inputs,
        );
        expect(notices[0]!.kind).toBe("mismatch");
        expect(notices[0]!.text).toBe("Batch inputs must have matching sizes: Input reads (2), Reverse reads (3).");
    });

    it("falls back to the parameter name for an input without a label", () => {
        const notices = jobCountNotices(expansion({ job_count: 0, inputs: [batched("cond|missing", 0)] }), inputs);
        expect(notices[0]!.text).toBe("No jobs will run because a batch input is empty: cond|missing.");
    });

    it("reports a structural mismatch when sizes agree", () => {
        const notices = jobCountNotices(
            expansion({ reason: "batch_mismatch", inputs: [batched("reads", 3), batched("extra", 3)] }),
            inputs,
        );
        expect(notices[0]!.text).not.toContain("(3)");
        expect(notices[0]!.text).toContain("different structures: Input reads, Extra.");
    });

    it("notes when the count waits on a collection", () => {
        const notices = jobCountNotices(expansion({ reason: "inputs_not_ready" }), inputs);
        expect(notices).toEqual([
            {
                variant: "muted",
                kind: "notReady",
                text: "Job count will be available once the selected collection is ready.",
            },
        ]);
    });

    it("warns that remapping rejects more than one job", () => {
        const many = expansion({ job_count: 4, inputs: [batched("reads", 4)] });
        expect(jobCountNotices(many, inputs, true).map((n) => n.kind)).toEqual(["count", "remap"]);
        expect(jobCountNotices(many, inputs, false).map((n) => n.kind)).toEqual(["count"]);
        const single = expansion({ job_count: 1, inputs: [batched("reads", 1)] });
        expect(jobCountNotices(single, inputs, true)).toEqual([]);
    });

    it("qualifies inputs in sections and repeats with their enclosing titles", () => {
        const notices = jobCountNotices(
            expansion({
                reason: "batch_mismatch",
                inputs: [batched("advanced|mask", 2), batched("queries_1|input2", 3)],
            }),
            inputs,
        );
        expect(notices[0]!.text).toBe(
            "Batch inputs must have matching sizes: Advanced › Select (2), 2: Query › Select (3).",
        );
    });
});

describe("runBlockedReason", () => {
    it("blocks when the server says no jobs would run", () => {
        expect(runBlockedReason(expansion({ job_count: 0, inputs: [batched("extra", 0)] }))).toBe(
            "No jobs would run because a batch input is empty.",
        );
    });

    it("blocks on a batch mismatch", () => {
        const mismatch = expansion({ reason: "batch_mismatch", inputs: [batched("reads", 2), batched("extra", 3)] });
        expect(runBlockedReason(mismatch)).toBe("Batch inputs must match before the tool can run.");
    });

    it("blocks remapping onto more than one job", () => {
        const many = expansion({ job_count: 4, inputs: [batched("reads", 4)] });
        expect(runBlockedReason(many, true)).toBe(
            "Remapping replaces a single job, but this request would run several jobs.",
        );
        expect(runBlockedReason(many, false)).toBeUndefined();
        expect(runBlockedReason(expansion({ job_count: 1, inputs: [batched("reads", 1)] }), true)).toBeUndefined();
    });

    it("never blocks on an unknown or pending count", () => {
        expect(runBlockedReason(undefined)).toBeUndefined();
        expect(runBlockedReason(expansion({ reason: "unknown" }), true)).toBeUndefined();
        expect(runBlockedReason(expansion({ reason: "inputs_not_ready" }), true)).toBeUndefined();
    });
});
