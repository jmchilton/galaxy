import { describe, expect, it } from "vitest";

import type { Rectangle } from "@/utils/geometry";

import {
    EMBEDDED_LAYOUT_GAP as GAP,
    type EmbeddedLayoutResult,
    type EmbeddedNodeRequest,
    type LayoutEdge,
    layoutEmbeddedOutputs,
    type LayoutNode,
} from "./embeddedOutputLayout";

function node(id: number, x: number, y: number, width = 200, height = 100): LayoutNode {
    return { id, x, y, width, height };
}

function card(sourceId: number, width = 400, height = 300, key = `${sourceId}`): EmbeddedNodeRequest {
    return { key, sourceId, width, height };
}

function overlaps(a: Rectangle, b: Rectangle) {
    return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/** Every pair of rectangles in the result is disjoint, except steps the author already overlapped */
function expectNoNewOverlaps(original: LayoutNode[], result: EmbeddedLayoutResult) {
    const rects: [string, Rectangle][] = [
        ...original.map((n): [string, Rectangle] => [`step ${n.id}`, result.nodes[n.id]!]),
        ...Object.entries(result.embedded).map(([key, rect]): [string, Rectangle] => [`card ${key}`, rect]),
    ];
    rects.forEach(([aName, a], i) =>
        rects.slice(i + 1).forEach(([bName, b], j) => {
            const authorOverlap = i + 1 + j < original.length && overlaps(original[i]!, original[i + 1 + j]!);
            if (!authorOverlap) {
                expect(overlaps(a, b), `${aName} overlaps ${bName}`).toBe(false);
            }
        }),
    );
}

/** Each card sits just right of its source, the first level with its top and the rest stacked below */
function expectCardsBesideSources(requests: EmbeddedNodeRequest[], result: EmbeddedLayoutResult) {
    const nextTop = new Map<number, number>();
    for (const request of requests) {
        const source = result.nodes[request.sourceId]!;
        const top = nextTop.get(request.sourceId) ?? source.y;
        expect(result.embedded[request.key], `card ${request.key}`).toEqual({
            x: source.x + source.width + GAP,
            y: top,
            width: request.width,
            height: request.height,
        });
        nextTop.set(request.sourceId, top + request.height + GAP);
    }
}

/** Steps only ever move right, and steps sharing a row keep their left-to-right order */
function expectNudgedRight(nodes: LayoutNode[], result: EmbeddedLayoutResult) {
    for (const a of nodes) {
        const moved = result.nodes[a.id]!;
        expect(moved.y, `step ${a.id} stays in its row`).toBe(a.y);
        expect(moved.x, `step ${a.id} never moves left`).toBeGreaterThanOrEqual(a.x);
        for (const b of nodes) {
            const shareRow = a.y < b.y + b.height && b.y < a.y + a.height;
            if (shareRow && a.x < b.x) {
                expect(moved.x, `step ${a.id} stays left of step ${b.id}`).toBeLessThan(result.nodes[b.id]!.x);
            }
        }
    }
}

function movedSteps(nodes: LayoutNode[], result: EmbeddedLayoutResult) {
    return nodes.filter((n) => result.nodes[n.id]!.x !== n.x).map((n) => n.id);
}

function expectNudged(nodes: LayoutNode[], requests: EmbeddedNodeRequest[], edges: LayoutEdge[] = []) {
    const result = layoutEmbeddedOutputs(nodes, requests, edges);
    expectNoNewOverlaps(nodes, result);
    expectCardsBesideSources(requests, result);
    expectNudgedRight(nodes, result);
    return result;
}

describe("layoutEmbeddedOutputs", () => {
    it("places the embedded node beside its source and pushes the downstream chain along", () => {
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 600, 0)];
        const result = expectNudged(
            nodes,
            [card(0)],
            [
                { from: 0, to: 1 },
                { from: 1, to: 2 },
            ],
        );

        expect(result.embedded["0"]).toEqual({ x: 220, y: 0, width: 400, height: 300 });
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
        expect(result.nodes[1]!.x).toBe(640);
        // both downstream nodes shift by the same amount: the chain keeps its shape
        expect(result.nodes[2]!.x - result.nodes[1]!.x).toBe(300);
    });

    it("keeps a row's steps in order and the gap apart when pushing them, without edges", () => {
        // steps 1 and 2 are both in the embedded node's rows; step 1 queues behind it and step 2 behind step 1
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 600, 0)];
        const result = expectNudged(nodes, [card(0)]);
        expect(result.nodes[1]!.x).toBe(220 + 400 + GAP);
        expect(result.nodes[2]!.x).toBe(220 + 400 + GAP + 200 + GAP);
    });

    it("leaves steps outside the embedded node's rows alone", () => {
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 300, 1000)];
        const result = expectNudged(nodes, [card(0)]);
        expect(result.nodes[2]).toMatchObject({ x: 300, y: 1000 });
        expect(movedSteps(nodes, result)).toEqual([1]);
    });

    it("pushes a step in a lower row past an embedded node that reaches down to it", () => {
        // step 1 is a row below the source, but under the tall embedded node
        const nodes = [node(0, 0, 0), node(1, 260, 150)];
        const result = expectNudged(nodes, [card(0)]);
        expect(result.nodes[1]!.x).toBe(220 + 400 + GAP);
    });

    it("nudges the source instead when a step from another row ends just left of the embedded node", () => {
        // step 1 ends 10px inside the gap before the embedded node; moving the source 10px clears it
        const nodes = [node(0, 0, 0), node(1, 10, 150)];
        const result = expectNudged(nodes, [card(0)]);
        expect(result.nodes[1]).toMatchObject({ x: 10, y: 150 });
        expect(result.nodes[0]!.x).toBe(10);
    });

    it("stacks several outputs of one step below each other, clearing the widest", () => {
        const nodes = [node(0, 0, 0), node(1, 300, 0)];
        const result = expectNudged(nodes, [card(0, 400, 300, "a"), card(0, 200, 200, "b")]);
        expect(result.embedded.b).toMatchObject({ x: 220, y: 320 });
        expect(result.nodes[1]!.x).toBe(220 + 400 + GAP);
    });

    it("pushes a step that starts right at its source's edge past the embedded node", () => {
        // the step settles where the source's embedded nodes start, so the source must settle first
        const nodes = [node(0, 200, 0), node(1, 0, 0)];
        const result = expectNudged(nodes, [card(1)]);
        expect(result.nodes[0]!.x).toBe(220 + 400 + GAP);
    });

    it("moves the later source when two embedded nodes collide, keeping each beside its source", () => {
        // step 1 sits above step 0's card, but its own card reaches down into it
        const nodes = [node(0, 0, 0), node(1, 100, -250)];
        const result = expectNudged(nodes, [card(0), card(1)]);
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
        expect(result.embedded["1"]).toMatchObject({ x: 220 + 400 + GAP, y: -250 });
    });

    it("keeps two sources' embedded nodes the gap apart vertically too", () => {
        // step 1's card would end 10px above step 0's card
        const nodes = [node(0, 0, 0), node(1, 100, -310)];
        const result = expectNudged(nodes, [card(0), card(1)]);
        expect(result.embedded["1"]).toMatchObject({ x: 220 + 400 + GAP, y: -310 });
    });

    it("doesn't carry along a step whose input doesn't end left of it", () => {
        // step 2 is fed by step 1 from above and starts under it, below the embedded node's rows
        const nodes = [node(0, 0, 0), node(1, 300, 0), node(2, 350, 330)];
        const result = expectNudged(nodes, [card(0)], [{ from: 1, to: 2 }]);
        expect(movedSteps(nodes, result)).toEqual([1]);
    });

    it("pushes a downstream step that starts in the gap before the embedded node past it, once", () => {
        // step 1 is fed by step 0 and starts between step 0 and its card, a row below
        const nodes = [node(0, 0, 0), node(1, 205, 150)];
        const result = expectNudged(nodes, [card(0)], [{ from: 0, to: 1 }]);
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
        expect(result.nodes[1]!.x).toBe(220 + 400 + GAP);
    });

    it("settles steps in adjacent rows whose embedded nodes each reach into the other's row", () => {
        // a source with two stacked cards above a source with one, both in one column
        const nodes = [node(0, 600, 600, 144, 57), node(1, 575, 660, 144, 50)];
        const requests = [card(0, 260, 170, "a"), card(0, 260, 170, "b"), card(1, 260, 170)];
        const result = expectNudged(nodes, requests);
        expect(result.nodes[1]).toMatchObject({ x: 575, y: 660 });
        expect(result.nodes[0]!.x).toBe(575 + 144 + GAP + 260 + GAP);
    });

    it("keeps pre-existing overlaps instead of spreading the workflow out", () => {
        const nodes = [node(0, 0, 0), node(1, 500, 500), node(2, 550, 520)];
        const result = layoutEmbeddedOutputs(nodes, [card(0, 100, 100)]);
        expect(movedSteps(nodes, result)).toEqual([]);
    });

    it("moves a step the author placed overlapping a source in its row past the source's embedded node", () => {
        // the steps overlap by 44px; the card beside the source would cover the second one
        const nodes = [node(0, 0, 0, 144, 55), node(1, 100, 0, 144, 55)];
        const result = layoutEmbeddedOutputs(nodes, [card(0, 260, 170)]);
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
        expect(result.nodes[1]).toMatchObject({ x: 144 + GAP + 260 + GAP, y: 0 });
        expect(overlaps(result.nodes[1]!, result.embedded["0"]!)).toBe(false);
    });

    it("doesn't spread steps the author placed closer than the gap", () => {
        const nodes = [node(0, 0, 0), node(1, 210, 0), node(2, 420, 0)];
        const result = layoutEmbeddedOutputs(nodes, []);
        expect(movedSteps(nodes, result)).toEqual([]);
    });

    describe("a step that grew", () => {
        /** A step shown larger than the 200×100 it has in the author's layout */
        function grown(id: number, x: number, y: number, width: number, height: number): LayoutNode {
            return { ...node(id, x, y, width, height), grewFrom: { width: 200, height: 100 } };
        }

        it("pushes the next step in its row along, leaving steps outside its rows alone", () => {
            const nodes = [grown(0, 0, 0, 400, 300), node(1, 250, 0), node(2, 250, 400)];
            const result = expectNudged(nodes, []);
            expect(result.nodes[1]).toMatchObject({ x: 400 + GAP, y: 0 });
            expect(overlaps(result.nodes[0]!, result.nodes[1]!)).toBe(false);
            expect(result.nodes[2]).toMatchObject({ x: 250, y: 400 });
        });

        it("keeps the spacing the author left tighter than the gap", () => {
            const nodes = [grown(0, 0, 0, 400, 100), node(1, 210, 0)];
            const result = expectNudged(nodes, []);
            expect(result.nodes[1]!.x).toBe(400 + 10);
        });

        it("pushes a step it grew down into past it, by the full gap", () => {
            // the steps shared no rows in the author's layout, and start at the same x
            const nodes = [grown(0, 0, 0, 300, 250), node(1, 0, 200)];
            const result = expectNudged(nodes, []);
            expect(result.nodes[1]).toMatchObject({ x: 300 + GAP, y: 200 });
        });

        it("carries along a step its edge flowed to in the author's layout", () => {
            // step 1 grew past the start of the step it feeds, in another row; step 0's card pushes step 1
            const nodes = [node(0, 0, 0), grown(1, 300, 0, 400, 300), node(2, 550, 400)];
            const result = expectNudged(nodes, [card(0)], [{ from: 1, to: 2 }]);
            expect(result.nodes[1]!.x).toBe(220 + 400 + GAP);
            expect(result.nodes[2]!.x - result.nodes[1]!.x).toBe(550 - 300);
        });

        it.each([
            [0, 55],
            [3, 55],
            [5, 55],
            [0, 45],
            [3, 45],
        ])(
            "doesn't overlap a step placed %ipx below its shrunk size, given a base height of %i (exact or under)",
            (below, baseHeight) => {
                // a 144×55 step grew to 260×171; the next step started just below it, at the same x
                const nodes = [
                    { ...node(0, 0, 0, 260, 171), grewFrom: { width: 144, height: baseHeight } },
                    node(1, 0, 55 + below, 144, 55),
                ];
                const result = expectNudged(nodes, []);
                expect(result.nodes[1]!.x).toBe(260 + GAP);
            },
        );

        it("keeps its own embedded nodes beside its grown edge", () => {
            const nodes = [grown(0, 0, 0, 300, 200), node(1, 250, 0)];
            const result = expectNudged(nodes, [card(0)]);
            expect(result.embedded["0"]).toMatchObject({ x: 300 + GAP, y: 0 });
            expect(result.nodes[1]!.x).toBe(300 + GAP + 400 + GAP);
        });
    });

    it("ignores outputs whose source step is missing", () => {
        const result = layoutEmbeddedOutputs([node(0, 0, 0)], [card(7)]);
        expect(result.embedded).toEqual({});
        expect(result.nodes[0]).toMatchObject({ x: 0, y: 0 });
    });

    it("on the invocation graph test workflow, moves only the steps in the cards' way", () => {
        // three input rows feeding table, image and text branches, steps shrunk as in the embedded view
        const nodes = [
            node(0, 0, 0, 144, 55),
            node(1, 0, 220, 144, 55),
            node(2, 0, 420, 144, 55),
            node(3, 520, 420, 144, 55),
            node(4, 260, 0, 144, 55),
            node(5, 260, 110, 144, 55),
            node(6, 260, 230, 144, 55),
            node(7, 260, 420, 144, 55),
            node(8, 520, 110, 144, 55),
            node(9, 780, 50, 144, 55),
        ];
        const edges = [
            [0, 4],
            [0, 5],
            [1, 6],
            [2, 7],
            [5, 8],
            [8, 9],
            [4, 9],
        ].map(([from, to]) => ({ from: from!, to: to! }));
        const requests = [4, 8, 6, 3, 9].map((id) => card(id, 260, 170));
        requests.push(card(7, 260, 120));

        const result = expectNudged(nodes, requests, edges);
        // the inputs and the first tool column stay put
        expect(movedSteps(nodes, result)).toEqual([3, 8, 9]);
    });

    it("on an IWC layout (CUT&RUN), keeps every card beside its source and the steps before the cards in place", () => {
        // positions and connections from IWC's cutandrun workflow, steps shrunk as in the embedded view
        const positions: [number, number][] = [
            [0, 268],
            [22, 375],
            [62, 483],
            [128, 589],
            [176, 689],
            [228, 780],
            [288, 180],
            [559, 102],
            [834, 23],
            [1112, 64],
            [1387, 37],
            [1656, 3],
            [1946, 0],
            [1945, 139],
            [1936, 415],
        ];
        const nodes = positions.map(([x, y], id) => node(id, x, y, 144, 55));
        const edges = [
            [0, 6],
            [1, 6],
            [2, 6],
            [6, 7],
            [3, 7],
            [7, 8],
            [8, 9],
            [9, 10],
            [5, 11],
            [4, 11],
            [10, 11],
            [11, 12],
            [11, 13],
            [6, 14],
            [7, 14],
            [9, 14],
            [11, 14],
        ].map(([from, to]) => ({ from: from!, to: to! }));
        // mapping stats, two from deduplication, three from the peak caller, its report and bigwig, two MultiQC
        const requests = [7, 9, 9, 11, 11, 11, 12, 13, 14, 14].map((id, index) => card(id, 260, 170, `${id}-${index}`));

        const result = expectNudged(nodes, requests, edges);
        for (const id of [0, 1, 2, 3, 4, 5, 6, 7]) {
            expect(result.nodes[id], `step ${id}`).toMatchObject({ x: nodes[id]!.x, y: nodes[id]!.y });
        }
    });
});
