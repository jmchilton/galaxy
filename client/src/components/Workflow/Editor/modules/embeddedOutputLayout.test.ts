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
});
