import { format, parseISO } from "date-fns";
import { computed, type Ref, ref, watch } from "vue";

import { type ExecutionJobsSource, useExecutionJobs } from "@/components/History/Graph/useExecutionJobs";

export interface SelectOption {
    value: string;
    text: string;
}

export function useMappingJobs(
    singleJobId: Ref<string | undefined>,
    implicitCollectionJobsId: Ref<string | undefined>,
) {
    const selectedJob = ref<string | undefined>(undefined);
    const targetJobId = computed<string | undefined>(() => {
        if (singleJobId.value) {
            return singleJobId.value;
        } else {
            return selectedJob.value;
        }
    });
    const source = computed<ExecutionJobsSource | undefined>(() =>
        implicitCollectionJobsId.value
            ? { implicitCollectionJobsId: implicitCollectionJobsId.value, recentlyUpdatedFirst: true }
            : undefined,
    );
    const { jobs } = useExecutionJobs(source);
    const selectJobOptions = computed<SelectOption[]>(() =>
        jobs.value.map((job, index) => {
            const isoCreateTime = parseISO(`${job.create_time}Z`);
            const prettyTime = format(isoCreateTime, "eeee MMM do H:mm:ss yyyy zz");
            return { value: job.id, text: `${index + 1}: ${prettyTime}` };
        }),
    );
    watch(jobs, (loaded) => {
        if (loaded[0]) {
            selectedJob.value = loaded[0].id;
        }
    });
    return { selectJobOptions, selectedJob, targetJobId };
}
