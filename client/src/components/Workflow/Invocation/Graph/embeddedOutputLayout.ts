/**
 * Makes room for embedded output nodes without re-laying out the workflow.
 *
 * Each embedded node is pinned to the right of its source step (several outputs of one step stack
 * downwards), and steps are pushed right just enough to clear them, and any step that grew (a step
 * shown as its preferred output). Steps never move vertically and never move left, so the
 * arrangement users remember is kept; only horizontal space is added.
 */
import type { Rectangle } from "@/utils/geometry";

/** Space kept between a step and its embedded nodes, and between nodes pushed beside each other */
export const EMBEDDED_LAYOUT_GAP = 20;

export interface LayoutNode extends Rectangle {
    id: number;
    /** The size the node grew from, when it is shown larger than in the author's layout (a step shown as its
     * preferred output); tells the overlaps and spacing the author made from those the growth made */
    grewFrom?: { width: number; height: number };
}

export interface EmbeddedNodeRequest {
    key: string;
    sourceId: number;
    width: number;
    height: number;
}

export interface LayoutEdge {
    from: number;
    to: number;
}

export interface EmbeddedLayoutResult {
    nodes: Record<number, Rectangle>;
    embedded: Record<string, Rectangle>;
}

/** The embedded nodes beside one step, stacked downwards from its top */
interface Stack {
    cards: { key: string; width: number; height: number; offset: number }[];
    width: number;
    height: number;
}

/** A vertical extent on the graph */
interface Rows {
    top: number;
    bottom: number;
}

function rowsOverlap(a: Rows, b: Rows, margin = 0) {
    return a.top < b.bottom + margin && b.top < a.bottom + margin;
}

function rowsOf(step: LayoutNode): Rows {
    return { top: step.y, bottom: step.y + step.height };
}

/** The rows a step had before it grew */
function baseRowsOf(step: LayoutNode): Rows {
    return { top: step.y, bottom: step.y + (step.grewFrom ?? step).height };
}

/** The width a step had before it grew */
function baseWidthOf(step: LayoutNode) {
    return (step.grewFrom ?? step).width;
}

/** The rows of a source's embedded nodes */
function stackRowsOf(source: LayoutNode, stack: Stack): Rows {
    return { top: source.y, bottom: source.y + stack.height };
}

export function layoutEmbeddedOutputs(
    nodes: LayoutNode[],
    requests: EmbeddedNodeRequest[],
    edges: LayoutEdge[] = [],
): EmbeddedLayoutResult {
    const gap = EMBEDDED_LAYOUT_GAP;
    const nodesById = new Map(nodes.map((node) => [node.id, node]));

    const stacks = new Map<number, Stack>();
    for (const request of requests) {
        if (!nodesById.has(request.sourceId)) {
            continue;
        }
        const stack = stacks.get(request.sourceId) ?? { cards: [], width: 0, height: 0 };
        const offset = stack.cards.length ? stack.height + gap : 0;
        stack.cards.push({ key: request.key, width: request.width, height: request.height, offset });
        stack.width = Math.max(stack.width, request.width);
        stack.height = offset + request.height;
        stacks.set(request.sourceId, stack);
    }
    /** The least `later.x - earlier.x` the rules allow, for a step settled after another */
    function minimumOffset(earlier: LayoutNode, later: LayoutNode) {
        const earlierStack = stacks.get(earlier.id);
        const laterStack = stacks.get(later.id);
        let offset = -Infinity;
        if (rowsOverlap(rowsOf(earlier), rowsOf(later))) {
            // steps sharing a row keep their order, at least the gap apart unless the author placed them closer
            // (overlaps the author made stay as they are); a step that grew into a row it wasn't in keeps the gap
            const authorSpacing = rowsOverlap(baseRowsOf(earlier), baseRowsOf(later))
                ? later.x - earlier.x - baseWidthOf(earlier)
                : gap;
            offset = earlier.width + Math.min(authorSpacing, gap);
        } else if (laterStack && rowsOverlap(rowsOf(earlier), stackRowsOf(later, laterStack), gap)) {
            // a source's embedded nodes stay clear of a step to their left in another row
            offset = earlier.width - later.width;
        }
        if (earlierStack && rowsOverlap(rowsOf(later), stackRowsOf(earlier, earlierStack), gap)) {
            // a step in the rows of a source's embedded nodes stays right of them
            offset = Math.max(offset, earlier.width + gap + earlierStack.width + gap);
        }
        if (
            earlierStack &&
            laterStack &&
            rowsOverlap(stackRowsOf(earlier, earlierStack), stackRowsOf(later, laterStack), gap)
        ) {
            // embedded nodes of two sources sharing rows: the later source's stay right of the others
            offset = Math.max(offset, earlier.width + earlierStack.width + gap - later.width);
        }
        return offset;
    }

    // edges that flow left to right in the author's layout keep their length, so a pushed step carries its
    // downstream steps
    const upstream = new Map<number, LayoutNode[]>();
    for (const edge of edges) {
        const from = nodesById.get(edge.from);
        const to = nodesById.get(edge.to);
        if (from && to && from.x + baseWidthOf(from) <= to.x) {
            upstream.set(to.id, [...(upstream.get(to.id) ?? []), from]);
        }
    }

    // Steps never change rows, so every rule is a fixed lower bound on a step's x relative to a step settled
    // before it. Settling steps from left to right satisfies them all in one pass, and a step only moves when
    // something settled before it needs the room. A source counts from its right edge, where its embedded nodes
    // start: a step below it that starts further left is settled first, and the source's embedded nodes keep clear
    // of it instead of pushing it past them. A step the author placed overlapping a source in its own row settles
    // after it, so it moves past the embedded nodes instead of being covered by them.
    const sources = nodes.filter((node) => stacks.has(node.id));
    const settleAt = new Map(
        nodes.map((node) => {
            if (stacks.has(node.id)) {
                return [node.id, node.x + node.width];
            }
            const overlapped = sources.filter(
                (s) => rowsOverlap(rowsOf(s), rowsOf(node)) && s.x <= node.x && node.x < s.x + s.width,
            );
            return [node.id, Math.max(node.x, ...overlapped.map((s) => s.x + s.width))];
        }),
    );
    const order = [...nodes].sort(
        (a, b) =>
            settleAt.get(a.id)! - settleAt.get(b.id)! ||
            Number(stacks.has(b.id)) - Number(stacks.has(a.id)) ||
            a.y - b.y ||
            a.id - b.id,
    );

    const x = new Map(nodes.map((node) => [node.id, node.x]));
    order.forEach((node, i) => {
        let settled = node.x;
        for (const earlier of order.slice(0, i)) {
            settled = Math.max(settled, x.get(earlier.id)! + minimumOffset(earlier, node));
        }
        for (const from of upstream.get(node.id) ?? []) {
            settled = Math.max(settled, x.get(from.id)! + node.x - from.x);
        }
        x.set(node.id, settled);
    });

    const result: EmbeddedLayoutResult = { nodes: {}, embedded: {} };
    for (const node of nodes) {
        result.nodes[node.id] = { x: x.get(node.id)!, y: node.y, width: node.width, height: node.height };
    }
    for (const [sourceId, stack] of stacks) {
        const source = result.nodes[sourceId]!;
        for (const card of stack.cards) {
            result.embedded[card.key] = {
                x: source.x + source.width + gap,
                y: source.y + card.offset,
                width: card.width,
                height: card.height,
            };
        }
    }
    return result;
}
