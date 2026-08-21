import { describe, expect, it } from "vitest";

import { connectionNameToInputPath, inputPathIsPrefix } from "./workflowInputPath";

describe("workflow input paths", () => {
    it("maps flat connection names to nested expression paths", () => {
        expect(connectionNameToInputPath("cond|input1")).toEqual(["cond", "input1"]);
    });

    it("compares complete path segments", () => {
        expect(inputPathIsPrefix(["cond"], ["cond", "input1"])).toBe(true);
        expect(inputPathIsPrefix(["cond", "input1"], ["cond", "input10"])).toBe(false);
    });
});
