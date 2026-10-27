import { type Ref, ref, watch } from "vue";

import { GalaxyApi } from "@/api";

/** Where a list of jobs comes from: one tool execution (tool request), or one mapped-over batch. */
export type ExecutionJobsSource =
    | { toolRequestId: string }
    /** `jobCount`, when known, fetches the whole batch rather than the index's default page. */
    | { implicitCollectionJobsId: string; jobCount?: number };

interface ExecutionJob {
    id: string;
}

const MESSAGES = {
    toolRequest: {
        failed: "Failed to load tool execution details.",
        empty: "No job associated with this tool execution.",
    },
    batch: { failed: "Failed to load the batch's jobs.", empty: "This batch has no jobs." },
};

async function fetchJobs(source: ExecutionJobsSource): Promise<ExecutionJob[] | undefined> {
    if ("toolRequestId" in source) {
        const { data, error } = await GalaxyApi().GET("/api/tool_requests/{id}", {
            params: { path: { id: source.toolRequestId } },
        });
        return error ? undefined : data.jobs;
    }
    const limit = source.jobCount ? { limit: source.jobCount } : {};
    const { data, error } = await GalaxyApi().GET("/api/jobs", {
        params: {
            query: { implicit_collection_jobs_id: source.implicitCollectionJobsId, order_by: "create_time", ...limit },
        },
    });
    // The index lists newest first; a batch reads in the order it was created.
    return error ? undefined : [...data].reverse();
}

/** Loads the jobs of a tool execution or a mapped-over batch; refetches when the source changes. */
export function useExecutionJobs(source: Ref<ExecutionJobsSource | undefined>) {
    const jobs = ref<ExecutionJob[]>([]);
    const loading = ref(false);
    const error = ref<string | null>(null);

    watch(
        source,
        async (current, _previous, onCleanup) => {
            let stale = false;
            onCleanup(() => {
                stale = true;
            });
            jobs.value = [];
            error.value = null;
            loading.value = false;
            if (!current) {
                return;
            }
            const messages = "toolRequestId" in current ? MESSAGES.toolRequest : MESSAGES.batch;
            loading.value = true;
            try {
                const loaded = await fetchJobs(current);
                if (stale) {
                    return;
                }
                if (!loaded) {
                    error.value = messages.failed;
                } else if (loaded.length) {
                    jobs.value = loaded;
                } else {
                    error.value = messages.empty;
                }
            } catch {
                if (!stale) {
                    error.value = messages.failed;
                }
            } finally {
                if (!stale) {
                    loading.value = false;
                }
            }
        },
        { immediate: true },
    );

    return { jobs, loading, error };
}
