import "@tests/vitest/mockHelpPopovers";

import { createTestingPinia } from "@pinia/testing";
import { getLocalVue, nth, withPlugins } from "@tests/vitest/helpers";
import { enableAutoUnmount, mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { http as mswHttp } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import jobResponse from "./testData/jobInformationResponse.json";

import JobInformation from "./JobInformation.vue";

const JOB_ID = "test_id";

const SELECTORS = {
    INFO_TABLE: "#job-information",
    JOB_MESSAGE: "#job-messages .job-message",
    JOB_STATE: "td[data-description='galaxy-job-state']",
    INVOCATION_LOOKUP_ERROR: "#invocation-lookup-error",
};

const localVue = getLocalVue();

const { server, http } = useServerMock();

enableAutoUnmount(afterEach);

function serveJob(job) {
    server.use(http.get("/api/jobs/{job_id}", ({ response }) => response(200).json(job)));
}

async function mountJobInformation() {
    const wrapper = mount(JobInformation, {
        props: { jobId: JOB_ID },
        global: withPlugins(localVue, createTestingPinia({ createSpy: vi.fn, stubActions: false })),
    });
    await flushPromises();
    return wrapper;
}

describe("JobInformation", () => {
    beforeEach(() => {
        server.use(
            http.get("/api/configuration/decode/{encoded_id}", ({ response }) => {
                return response(200).json({ decoded_id: 123 });
            }),
            http.get("/api/invocations", ({ response }) => {
                return response(200).json([]);
            }),
            http.get("/api/jobs/{job_id}/console_output", ({ response }) => {
                return response(200).json({ stdout: "stdout", stderr: "stderr" });
            }),
        );
        serveJob(jobResponse);
    });

    it("renders a row for each field the job has", async () => {
        const wrapper = await mountJobInformation();

        const infoTable = wrapper.find(SELECTORS.INFO_TABLE);
        expect(infoTable.exists()).toBe(true);
        expect(infoTable.findAll("tr").length).toBe(10);
    });

    it("renders the running job's stdout and stderr", async () => {
        const wrapper = await mountJobInformation();

        for (const stream of ["stdout", "stderr"]) {
            expect(wrapper.find(`#${stream} .code`).text()).toBe(stream);
        }
    });

    it("numbers each job message", async () => {
        const wrapper = await mountJobInformation();

        const messages = wrapper.findAll(SELECTORS.JOB_MESSAGE);
        expect(messages.length).toBe(jobResponse.job_messages.length);
        messages.forEach((message, index) => {
            expect(message.text()).toMatch(new RegExp(`^Job Message ${index + 1}:`));
        });
    });

    it("lists the fields of each structured job message", async () => {
        serveJob({
            ...jobResponse,
            job_messages: [
                { type: "regex", desc: "first problem", error_level: 2 },
                { type: "exit_code", desc: "second problem", error_level: 3 },
            ],
        });

        const wrapper = await mountJobInformation();

        const messages = wrapper.findAll(SELECTORS.JOB_MESSAGE);
        expect(messages.length).toBe(2);
        expect(nth(messages, 0).text()).toContain("Job Message 1:");
        expect(nth(messages, 0).text()).toContain("desc: first problem");
        expect(nth(messages, 1).text()).toContain("Job Message 2:");
        expect(nth(messages, 1).text()).toContain("desc: second problem");
    });

    it("explains stream read failures and displays structured diagnostics", async () => {
        const desc = "Job failed because the tool stdout file could not be read: No such file or directory";
        serveJob({
            ...jobResponse,
            state: "error",
            job_messages: [{ type: "stdio_read_error", stream: "stdout", errno: 2, error_level: 3, desc }],
        });

        const wrapper = await mountJobInformation();

        const message = wrapper.find(SELECTORS.JOB_MESSAGE).text();
        expect(message).toContain(desc);
        expect(message).toContain("type: stdio_read_error");
        expect(message).toContain("stream: stdout");
        expect(message).toContain("errno: 2");
    });

    it("renders the tool, job and copied-from ids and the job state from the API", async () => {
        const wrapper = await mountJobInformation();

        const infoTable = wrapper.find(SELECTORS.INFO_TABLE);
        const renderedFields = {
            "galaxy-tool-id": jobResponse.tool_id,
            "galaxy-tool-version": jobResponse.tool_version,
            "encoded-job-id": jobResponse.id,
            "encoded-copied-from-job-id": jobResponse.copied_from_job_id,
        };
        for (const [id, value] of Object.entries(renderedFields)) {
            // Contains rather than equals: ids are followed by their decoded value.
            expect(infoTable.find(`#${id}`).text()).toContain(value);
        }
        expect(wrapper.find(SELECTORS.JOB_STATE).exists()).toBe(true);
    });

    it("renders the job and reports an invocation lookup that fails to reach the server", async () => {
        server.use(mswHttp.get("/api/invocations", () => HttpResponse.error()));

        const wrapper = await mountJobInformation();

        expect(wrapper.find(SELECTORS.INFO_TABLE).exists()).toBe(true);
        expect(wrapper.find(SELECTORS.INVOCATION_LOOKUP_ERROR).text()).toContain(
            "Could not determine the workflow invocation",
        );
    });
});
