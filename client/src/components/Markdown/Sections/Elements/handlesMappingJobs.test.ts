import flushPromises from "flush-promises";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type EffectScope, effectScope, ref } from "vue";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import { useMappingJobs } from "./handlesMappingJobs";

const { server, http } = useServerMock();

// Created and last updated in different orders.
const BATCH_JOBS = [
    { id: "a", create_time: "2024-03-05T12:00:00", update_time: "2024-03-05T12:30:00" },
    { id: "b", create_time: "2024-03-05T12:10:00", update_time: "2024-03-05T12:05:00" },
    { id: "c", create_time: "2024-03-05T12:20:00", update_time: "2024-03-05T12:20:00" },
];
const OTHER_BATCH_JOBS = [{ id: "k", create_time: "2024-03-06T12:00:00", update_time: "2024-03-06T12:00:00" }];

let requests: URLSearchParams[];
let fail: boolean;
let scope: EffectScope | undefined;

beforeEach(() => {
    requests = [];
    fail = false;
    server.use(
        http.untyped.get("/api/jobs", ({ request }) => {
            const query = new URL(request.url).searchParams;
            requests.push(query);
            if (fail) {
                return HttpResponse.json({ err_msg: "nope", err_code: 500 }, { status: 500 });
            }
            const jobs = query.get("implicit_collection_jobs_id") === "icj1" ? BATCH_JOBS : OTHER_BATCH_JOBS;
            // newest first by the requested time, as the index sorts
            const orderBy = (query.get("order_by") ?? "update_time") as "create_time" | "update_time";
            const sorted = [...jobs].sort((x, y) => y[orderBy].localeCompare(x[orderBy]));
            return HttpResponse.json(sorted.map((job) => ({ ...job, model_class: "Job", state: "ok" })));
        }),
    );
});

afterEach(() => {
    scope?.stop();
    scope = undefined;
});

function useJobs(jobId?: string, implicitCollectionJobsId?: string) {
    const singleJobId = ref(jobId);
    const icjId = ref(implicitCollectionJobsId);
    scope = effectScope();
    const result = scope.run(() => useMappingJobs(singleJobId, icjId))!;
    return { ...result, icjId };
}

describe("useMappingJobs", () => {
    it("numbers a batch's jobs most recently updated first and selects the first", async () => {
        const { selectJobOptions, selectedJob, targetJobId } = useJobs(undefined, "icj1");
        await flushPromises();
        expect(selectJobOptions.value.map((option) => option.value)).toEqual(["a", "c", "b"]);
        selectJobOptions.value.forEach((option, index) => {
            expect(option.text).toMatch(new RegExp(`^${index + 1}: \\w+day Mar \\d+\\w\\w \\d+:\\d\\d:00 2024`));
        });
        expect(selectedJob.value).toBe("a");
        expect(targetJobId.value).toBe("a");
    });

    it("targets the job the user selects", async () => {
        const { selectedJob, targetJobId } = useJobs(undefined, "icj1");
        await flushPromises();
        selectedJob.value = "b";
        expect(targetJobId.value).toBe("b");
    });

    it("selects the first job of a new batch", async () => {
        const { selectJobOptions, selectedJob, icjId } = useJobs(undefined, "icj1");
        await flushPromises();
        selectedJob.value = "b";
        icjId.value = "icj2";
        await flushPromises();
        expect(selectJobOptions.value.map((option) => option.value)).toEqual(["k"]);
        expect(selectedJob.value).toBe("k");
    });

    it("targets a single job without fetching a batch", async () => {
        const { selectJobOptions, targetJobId } = useJobs("j1");
        await flushPromises();
        expect(targetJobId.value).toBe("j1");
        expect(selectJobOptions.value).toEqual([]);
        expect(requests).toHaveLength(0);
    });

    it("offers no jobs when the batch fails to load", async () => {
        fail = true;
        const { selectJobOptions, targetJobId } = useJobs(undefined, "icj1");
        await flushPromises();
        expect(requests).toHaveLength(1);
        expect(selectJobOptions.value).toEqual([]);
        expect(targetJobId.value).toBeUndefined();
    });
});
