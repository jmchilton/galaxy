import { afterEach, describe, expect, it, vi } from "vitest";

import { downloadBlob } from "./download";

afterEach(() => {
    vi.restoreAllMocks();
});

describe("downloadBlob", () => {
    it("saves the blob under the file name through a temporary link", () => {
        const blob = new Blob(["a,b\r\n"], { type: "text/csv" });
        URL.createObjectURL = vi.fn(() => "blob:test");
        URL.revokeObjectURL = vi.fn();
        const clicked: { href: string; download: string; attached: boolean }[] = [];
        vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
            clicked.push({ href: this.href, download: this.download, attached: document.body.contains(this) });
        });
        downloadBlob(blob, "runs.csv");
        expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
        expect(clicked).toEqual([{ href: "blob:test", download: "runs.csv", attached: true }]);
        expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test");
        expect(document.querySelectorAll("a[download]")).toHaveLength(0);
    });
});
