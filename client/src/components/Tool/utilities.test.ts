import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { copyLink } from "./utilities";

const writeText = vi.fn();

describe("copyLink", () => {
    let clipboardDescriptor: PropertyDescriptor | undefined;

    beforeEach(() => {
        clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, "clipboard");
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { writeText },
        });
        writeText.mockClear();
        writeText.mockResolvedValue(undefined);
    });

    afterEach(() => {
        if (clipboardDescriptor) {
            Object.defineProperty(navigator, "clipboard", clipboardDescriptor);
        } else {
            Reflect.deleteProperty(navigator, "clipboard");
        }
    });

    it("should copy the link to the clipboard", () => {
        const toolId = "MyToolId";
        copyLink(toolId);
        expect(writeText).toHaveBeenCalledTimes(1);
        expect(writeText).toHaveBeenCalledWith(expect.stringContaining(toolId));
        expect(writeText).toHaveBeenCalledWith(expect.not.stringContaining("/root?"));
    });

    it("should encode the tool id with spaces", () => {
        const toolId = "My Tool Id";
        copyLink(toolId);
        expect(writeText).toHaveBeenCalledTimes(1);
        expect(writeText).toHaveBeenCalledWith(expect.stringContaining("My%20Tool%20Id"));
    });

    it("should not encode the character '+' in the tool id", () => {
        const toolId = "My Tool Id+1";
        copyLink(toolId);
        expect(writeText).toHaveBeenCalledTimes(1);
        expect(writeText).toHaveBeenCalledWith(expect.stringContaining("My%20Tool%20Id+1"));
    });
});
