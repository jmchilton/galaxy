import { describe, expect, it } from "vitest";

import { centerRouterViewKey } from "./routerViewKey";

function route(fullPath: string, meta: Record<string, unknown> = {}) {
    return { path: fullPath.split("?")[0]!, fullPath, meta };
}

describe("centerRouterViewKey", () => {
    it("remounts on any path or query change by default", () => {
        expect(centerRouterViewKey(route("/histories/list?page=1"))).not.toBe(
            centerRouterViewKey(route("/histories/list?page=2")),
        );
        expect(centerRouterViewKey(route("/datasets/1/details"))).not.toBe(
            centerRouterViewKey(route("/datasets/2/details")),
        );
    });

    it("keeps one GalaxyAI instance across its routes", () => {
        expect(centerRouterViewKey(route("/galaxyai"))).toBe(centerRouterViewKey(route("/galaxyai/abc")));
    });

    it("keeps routes that ask for it mounted across query changes, but not path changes", () => {
        const meta = { reuseOnQueryChange: true };
        expect(centerRouterViewKey(route("/comparisons?kind=tool_runs&tool_id=cat1", meta))).toBe(
            centerRouterViewKey(route("/comparisons?kind=tool_runs&tool_id=cat1&states=ok", meta)),
        );
        expect(centerRouterViewKey(route("/a?x=1", meta))).not.toBe(centerRouterViewKey(route("/b?x=1", meta)));
    });
});
