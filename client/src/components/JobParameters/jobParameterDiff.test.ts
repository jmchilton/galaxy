import { describe, expect, it } from "vitest";

import type { JobParameter } from "./jobParameterDiff";
import { diffJobParameters } from "./jobParameterDiff";

function p(text: string, value: JobParameter["value"], depth = 1): JobParameter {
    return { text, value, depth };
}

const dataset = (id: string, hid: number) => [{ src: "hda" as const, id, hid, name: `data ${hid}` }];

describe("diffJobParameters", () => {
    it("pairs parameters by their path and marks values that differ", () => {
        const a = [p("Lines", 10), p("Section", null), p("Mode", "fast", 2), p("Input", dataset("x", 1))];
        const b = [p("Lines", 12), p("Section", null), p("Mode", "fast", 2), p("Input", dataset("x", 1))];
        const diff = diffJobParameters(a, b);
        expect(diff.map((entry) => [entry.path, entry.a, entry.b, entry.differs])).toEqual([
            ["Lines", "10", "12", true],
            ["Section", "", "", false],
            ["Section › Mode", "fast", "fast", false],
            ["Input", "1: data 1", "1: data 1", false],
        ]);
        expect(diff[2]!).toMatchObject({ label: "Mode", depth: 2 });
    });

    it("compares datasets by id, not by name", () => {
        const [entry] = diffJobParameters([p("Input", dataset("x", 1))], [p("Input", dataset("y", 1))]);
        expect(entry!.differs).toBe(true);
    });

    it("keeps same-named parameters under different sections apart", () => {
        const a = [p("One", null), p("Size", 1, 2), p("Two", null), p("Size", 2, 2)];
        const b = [p("One", null), p("Size", 1, 2), p("Two", null), p("Size", 3, 2)];
        const diff = diffJobParameters(a, b).filter((entry) => entry.label === "Size");
        expect(diff.map((entry) => [entry.path, entry.differs])).toEqual([
            ["One › Size", false],
            ["Two › Size", true],
        ]);
    });

    it("lists parameters only one job has after the shared ones, as differing", () => {
        const diff = diffJobParameters([p("Old", 1)], [p("New", 2)]);
        expect(diff.map((entry) => [entry.path, entry.a, entry.b, entry.differs])).toEqual([
            ["Old", "1", undefined, true],
            ["New", undefined, "2", true],
        ]);
    });

    it("tells repeated paths apart by position", () => {
        const diff = diffJobParameters([p("Query", 1), p("Query", 2)], [p("Query", 1), p("Query", 5)]);
        expect(diff.map((entry) => entry.differs)).toEqual([false, true]);
    });
});

// As `summarize_job_parameters` lists them: plain parameters carry notes, a conditional's test row
// doesn't, and repeat members follow without a header row.
describe("diffJobParameters with repeats", () => {
    const plain = (text: string, value: JobParameter["value"], depth = 1) => ({ ...p(text, value, depth), notes: "" });
    const rows = (diff: ReturnType<typeof diffJobParameters>) =>
        diff.map((entry) => [entry.path, entry.a, entry.b, entry.differs]);

    it("gives members of a leading repeat a path without a phantom parent", () => {
        const a = [plain("Query", "x", 2), plain("Query", "y", 2), plain("Lines", 10)];
        const b = [plain("Query", "x", 2), plain("Lines", 10)];
        expect(rows(diffJobParameters(a, b))).toEqual([
            ["Query", "x", "x", false],
            ["Query", "y", undefined, true],
            ["Lines", "10", "10", false],
        ]);
    });

    it("doesn't nest repeat members under the plain parameter before them", () => {
        const diff = diffJobParameters([plain("Lines", 10), plain("Query", "x", 2)], [plain("Lines", 10)]);
        expect(rows(diff)).toEqual([
            ["Lines", "10", "10", false],
            ["Query", "x", undefined, true],
        ]);
    });

    it("pairs repeat members after a conditional whose case has a same-named child", () => {
        const a = [p("Mode", "advanced"), plain("Size", 5, 2), plain("Size", 1, 2), plain("Size", 2, 2)];
        const b = [p("Mode", "simple"), plain("Size", 1, 2), plain("Size", 3, 2)];
        expect(rows(diffJobParameters(a, b))).toEqual([
            ["Mode", "advanced", "simple", true],
            ["Mode › Size", "5", undefined, true],
            ["Mode › Size", "1", "1", false],
            ["Mode › Size", "2", "3", true],
        ]);
    });
});
