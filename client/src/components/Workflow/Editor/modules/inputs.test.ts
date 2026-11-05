import { describe, expect, it } from "vitest";

import { getWorkflowInputs } from "./inputs";

describe("getWorkflowInputs", () => {
    it("defaults new collection inputs to list", () => {
        const collectionInput = getWorkflowInputs().find((input) => input.title === "Input Dataset Collection");
        expect(collectionInput?.stateOverwrites).toEqual({ collection_type: "list" });
    });
});
