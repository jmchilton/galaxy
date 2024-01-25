/**
 * Requests jobs
 * Requests response generated by a tool run
 */

import { defineStore } from "pinia";
import Vue from "vue";
import { getAppRoot } from "@/onload/loadConfig";
import axios from "axios";

/* interfaces */
interface Job {
    id: string;
}
interface JobDef {
    tool_id: string;
}
interface JobResponse {
    produces_entry_points: boolean;
    jobs: Array<Job>;
}
interface ResponseVal {
    jobDef: JobDef;
    jobResponse: JobResponse;
    toolName: string;
    usedToolRequest: boolean;
}

export const useJobStore = defineStore("jobStore", {
    state: () => ({
        jobs: {} as { [index: string]: Job },
        response: {} as ResponseVal,
    }),
    getters: {
        getJob: (state) => {
            return (jobId: string) => state.jobs[jobId];
        },
        getLatestResponse: (state) => {
            return state.response;
        },
    },
    actions: {
        async fetchJob(jobId: string) {
            const { data } = await axios.get(`${getAppRoot()}api/jobs/${jobId}?full=true`);
            this.saveJobForJobId(jobId, data);
        },
        // Setters
        saveJobForJobId(jobId: string, job: Job) {
            Vue.set(this.jobs, jobId, job);
        },
        saveLatestResponse(response: ResponseVal) {
            this.response = response;
        },
    },
});
