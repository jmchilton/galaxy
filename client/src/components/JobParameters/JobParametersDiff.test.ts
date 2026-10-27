import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import type { JobParameter } from "./jobParameterDiff";

import JobParametersDiff from "./JobParametersDiff.vue";

const { server, http } = useServerMock();

const NOT_USED = "not used (parameter was added after this job was run)";

function display(lines: number, input: string) {
    const parameters: JobParameter[] = [
        { text: "Lines", depth: 1, value: lines },
        { text: "Input", depth: 1, value: [{ src: "hda", id: input, hid: 1, name: "reads" }] },
        { text: "Mode", depth: 1, value: "fast" },
    ];
    return { has_parameter_errors: false, outputs: {}, parameters };
}

beforeEach(() => {
    setActivePinia(createPinia());
    server.use(
        http.untyped.get("/api/jobs/a/parameters_display", () => HttpResponse.json(display(10, "x"))),
        http.untyped.get("/api/jobs/b/parameters_display", () => HttpResponse.json(display(12, "y"))),
        http.untyped.get("/api/jobs/old/parameters_display", () => {
            const old = display(10, "x");
            old.parameters[2] = { text: "Mode", depth: 1, notes: NOT_USED };
            return HttpResponse.json(old);
        }),
        http.untyped.get("/api/jobs/broken/parameters_display", () =>
            HttpResponse.json({ err_msg: "Job not accessible", err_code: 403 }, { status: 403 }),
        ),
    );
});

async function mountDiff(props: Record<string, unknown>) {
    const wrapper = mount(JobParametersDiff as object, { props: { labelA: "Run A", labelB: "Run B", ...props } });
    await flushPromises();
    return wrapper;
}

function lines(wrapper: Awaited<ReturnType<typeof mountDiff>>) {
    return wrapper.findAll("tbody tr").map((tr) => ({
        cells: tr.findAll("td").map((td) => td.text()),
        changed: tr.classes().includes("job-parameters-diff-changed"),
    }));
}

describe("JobParametersDiff", () => {
    it("shows both jobs' parameters side by side, marking those that differ", async () => {
        const wrapper = await mountDiff({ jobIdA: "a", jobIdB: "b" });
        expect(wrapper.findAll("thead th").map((th) => th.text())).toEqual(["Parameter", "Run A", "Run B"]);
        expect(lines(wrapper)).toEqual([
            { cells: ["Lines", "10", "12"], changed: true },
            { cells: ["Input", "1: reads", "1: reads"], changed: true },
            { cells: ["Mode", "fast", "fast"], changed: false },
        ]);
        expect(wrapper.find(".job-parameters-diff-summary").text()).toBe("2 of 3 parameters differ.");
    });

    it("shows only differences when asked", async () => {
        const wrapper = await mountDiff({ jobIdA: "a", jobIdB: "b", onlyDifferences: true });
        expect(lines(wrapper).map((line) => line.cells[0])).toEqual(["Lines", "Input"]);
    });

    it("says when every parameter matches", async () => {
        const wrapper = await mountDiff({ jobIdA: "a", jobIdB: "a", onlyDifferences: true });
        expect(wrapper.find(".job-parameters-diff-summary").text()).toBe("All parameters match.");
        expect(wrapper.find("table").exists()).toBe(false);
    });

    it("shows a parameter's notes where it has no value", async () => {
        const wrapper = await mountDiff({ jobIdA: "a", jobIdB: "old" });
        expect(lines(wrapper)[2]).toEqual({ cells: ["Mode", "fast", NOT_USED], changed: true });
    });

    it("shows a load error", async () => {
        const wrapper = await mountDiff({ jobIdA: "a", jobIdB: "broken" });
        expect(wrapper.text()).toContain("Job not accessible");
    });
});
