import { describe, expect, it } from "vitest";

import parameterSteps from "../test-data/parameter_steps.json";
import {
    type EmbeddedLayoutResult,
    layoutEmbeddedOutputs,
    type LayoutNode,
    type LayoutRect,
} from "./embeddedOutputLayout";

const GAP = 20;

function node(id: number, x: number, y: number, width = 200, height = 100): LayoutNode {
    return { id, x, y, width, height };
}

function overlaps(a: LayoutRect, b: LayoutRect) {
    return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

function allRects(result: EmbeddedLayoutResult) {
    return [...Object.values(result.nodes), ...Object.values(result.embedded)];
}

function expectNoNewOverlaps(original: LayoutNode[], result: EmbeddedLayoutResult) {
    const preExisting = new Set<string>();
    original.forEach((a, i) =>
        original.slice(i + 1).forEach((b) => overlaps(a, b) && preExisting.add(`${a.id}|${b.id}`)),
    );
    const nodeIds = original.map((n) => n.id);
    const rects = allRects(result);
    rects.forEach((a, i) =>
        rects.slice(i + 1).forEach((b, j) => {
            const ai = nodeIds[i];
            const bi = nodeIds[i + 1 + j];
            if (ai !== undefined && bi !== undefined && preExisting.has(`${ai}|${bi}`)) {
                return;
            }
            expect(overlaps(a, b), `overlap between rect ${i} and ${i + 1 + j}`).toBe(false);
        }),
    );
}

describe("layoutEmbeddedOutputs", () => {
    it("places the embedded node beside its source and pushes the downstream chain along", () => {
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 600, 0)];
        const result = layoutEmbeddedOutputs(
            nodes,
            [{ key: "out", sourceId: 0, width: 400, height: 300 }],
            [
                { from: 0, to: 1 },
                { from: 1, to: 2 },
            ],
            { gap: GAP },
        );

        expect(result.embedded.out).toEqual({ x: 220, y: 0, width: 400, height: 300 });
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
        expect(result.nodes[1]!.x).toBe(640);
        expect(result.nodes[2]!.x).toBeGreaterThanOrEqual(640 + 200 + GAP);
        // both downstream nodes shift by the same amount: the chain keeps its shape
        expect(result.nodes[2]!.x - result.nodes[1]!.x).toBe(300);
        expectNoNewOverlaps(nodes, result);
    });

    it("leaves nodes outside the embedded node's band alone", () => {
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 300, 1000)];
        const result = layoutEmbeddedOutputs(nodes, [{ key: "out", sourceId: 0, width: 400, height: 300 }], [], {
            gap: GAP,
        });
        expect(result.nodes[2]).toMatchObject({ x: 300, y: 1000 });
        expect(result.movedNodeIds).toEqual([1]);
    });

    it("only moves along the push axis and never backwards", () => {
        const nodes = [node(0, 0, 0), node(1, 0, 150), node(2, 0, 300)];
        const result = layoutEmbeddedOutputs(nodes, [{ key: "out", sourceId: 0, width: 400, height: 300 }], [], {
            direction: "down",
            gap: GAP,
        });
        expect(result.embedded.out).toMatchObject({ x: 0, y: 120 });
        for (const n of nodes) {
            expect(result.nodes[n.id]!.x).toBe(n.x);
            expect(result.nodes[n.id]!.y).toBeGreaterThanOrEqual(n.y);
        }
        // vertical order is kept
        expect(result.nodes[1]!.y).toBeLessThan(result.nodes[2]!.y);
        expectNoNewOverlaps(nodes, result);
    });

    it("keeps pre-existing overlaps instead of spreading the workflow out", () => {
        const nodes = [node(0, 0, 0), node(1, 500, 500), node(2, 550, 520)];
        const result = layoutEmbeddedOutputs(nodes, [{ key: "out", sourceId: 0, width: 100, height: 100 }]);
        expect(result.movedNodeIds).toEqual([]);
    });

    it("doesn't spread steps the author placed closer than the gap", () => {
        const nodes = [node(0, 0, 0), node(1, 0, 110), node(2, 0, 220)];
        const result = layoutEmbeddedOutputs(nodes, [], [], { gap: GAP });
        expect(result.movedNodeIds).toEqual([]);
    });

    it("makes room for a step that grew into its neighbours", () => {
        const nodes = [
            { ...node(0, 0, 0, 400, 300), baseWidth: 200, baseHeight: 100 },
            node(1, 250, 0),
            node(2, 250, 400),
        ];
        const result = layoutEmbeddedOutputs(nodes, [], [], { gap: GAP });
        expect(result.nodes[1]!.x).toBe(420);
        expect(result.nodes[2]).toMatchObject({ x: 250, y: 400 });
    });

    it("makes room for a step that grew down into the step below it", () => {
        const nodes = [{ ...node(0, 0, 0, 300, 250), baseWidth: 200, baseHeight: 100 }, node(1, 0, 200)];
        const result = layoutEmbeddedOutputs(nodes, [], [], { gap: GAP });
        expect(result.nodes[1]).toMatchObject({ x: 320, y: 200 });
    });

    it("nudges a real editor layout locally", () => {
        const nodes = Object.values(
            parameterSteps as Record<string, { id: number; position: { left: number; top: number } }>,
        ).map((step) => node(step.id, step.position.left, step.position.top, 180, 90));
        const sources = [6, 7];
        const result = layoutEmbeddedOutputs(
            nodes,
            sources.map((id) => ({ key: `${id}`, sourceId: id, width: 360, height: 240 })),
            [],
            { gap: GAP },
        );

        expectNoNewOverlaps(nodes, result);
        for (const n of nodes) {
            expect(result.nodes[n.id]!.y).toBe(n.y);
            expect(result.nodes[n.id]!.x).toBeGreaterThanOrEqual(n.x);
        }
        // local: most of the workflow doesn't move at all
        expect(result.movedNodeIds.length).toBeLessThan(nodes.length / 2);
    });

    describe.each(["right", "down"] as const)("on a branching workflow, nudging %s", (direction) => {
        // three input rows feeding table, image and text branches; every tool step is a workflow output
        const nodes = [
            node(0, 0, 0, 144, 60),
            node(1, 0, 220, 144, 60),
            node(2, 0, 420, 144, 60),
            node(3, 520, 420, 144, 60),
            node(4, 260, 0, 144, 60),
            node(5, 260, 110, 144, 60),
            node(6, 260, 230, 144, 60),
            node(7, 260, 420, 144, 60),
            node(8, 520, 110, 144, 60),
            node(9, 780, 50, 144, 60),
        ];
        const edges = [
            { from: 0, to: 4 },
            { from: 0, to: 5 },
            { from: 1, to: 6 },
            { from: 2, to: 7 },
            { from: 5, to: 8 },
            { from: 8, to: 9 },
            { from: 4, to: 9 },
        ];
        const requests = [4, 8, 6, 3, 9].map((id) => ({ key: `${id}`, sourceId: id, width: 360, height: 260 }));
        requests.push({ key: "7", sourceId: 7, width: 360, height: 170 });
        const result = layoutEmbeddedOutputs(nodes, requests, edges, { direction, gap: GAP });

        it("adds no overlaps", () => {
            expectNoNewOverlaps(nodes, result);
        });

        it("keeps the order of steps that share a row or column", () => {
            const axis = direction === "right" ? "x" : "y";
            const cross = direction === "right" ? "y" : "x";
            const crossExtent = direction === "right" ? "height" : "width";
            for (const a of nodes) {
                for (const b of nodes) {
                    const shareBand = a[cross] < b[cross] + b[crossExtent] && b[cross] < a[cross] + a[crossExtent];
                    if (shareBand && a[axis] < b[axis]) {
                        expect(result.nodes[a.id]![axis], `step ${a.id} stays before step ${b.id}`).toBeLessThan(
                            result.nodes[b.id]![axis],
                        );
                    }
                }
            }
        });
    });
});
