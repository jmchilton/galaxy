/**
 * Makes room for embedded output nodes without re-laying out the workflow.
 *
 * Each embedded node is placed beside its source step, then overlapping nodes are pushed
 * along a single axis. Nodes never move on the other axis and never move backwards, so
 * the relative arrangement users remember is kept; only the amount of space changes.
 */

export interface LayoutRect {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface LayoutNode extends LayoutRect {
    id: number;
    /** Size before the node grew (e.g. a step rendered as its preferred output); used to tell
     * overlaps the author made from overlaps the growth caused */
    baseWidth?: number;
    baseHeight?: number;
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

export type NudgeDirection = "right" | "down";

export interface EmbeddedLayoutOptions {
    direction?: NudgeDirection;
    gap?: number;
    maxIterations?: number;
}

export interface EmbeddedLayoutResult {
    nodes: Record<number, LayoutRect>;
    embedded: Record<string, LayoutRect>;
    /** Largest distance any step moved, useful to judge whether nudging stayed local */
    maxDisplacement: number;
    movedNodeIds: number[];
}

interface Item extends LayoutRect {
    kind: "node" | "embedded";
    key: string;
    sourceId?: number;
}

function overlaps(a: LayoutRect, b: LayoutRect, gap: number) {
    return (
        a.x < b.x + b.width + gap &&
        b.x < a.x + a.width + gap &&
        a.y < b.y + b.height + gap &&
        b.y < a.y + a.height + gap
    );
}

function pairKey(a: Item, b: Item) {
    return a.key < b.key ? `${a.key}|${b.key}` : `${b.key}|${a.key}`;
}

export function layoutEmbeddedOutputs(
    nodes: LayoutNode[],
    requests: EmbeddedNodeRequest[],
    edges: LayoutEdge[] = [],
    options: EmbeddedLayoutOptions = {},
): EmbeddedLayoutResult {
    const direction = options.direction ?? "right";
    const gap = options.gap ?? 20;
    const maxIterations = options.maxIterations ?? 1000;
    const axis: "x" | "y" = direction === "right" ? "x" : "y";
    const extent: "width" | "height" = direction === "right" ? "width" : "height";

    const nodeItems = new Map<number, Item>();
    for (const node of nodes) {
        nodeItems.set(node.id, { ...node, kind: "node", key: `n${node.id}` });
    }
    const items: Item[] = [...nodeItems.values()];

    // Pre-existing overlaps are the author's choice; don't "fix" them.
    const ignoredPairs = new Set<string>();
    const baseRects = nodes.map((node) => ({
        ...node,
        width: node.baseWidth ?? node.width,
        height: node.baseHeight ?? node.height,
    }));
    for (let i = 0; i < baseRects.length; i++) {
        for (let j = i + 1; j < baseRects.length; j++) {
            if (overlaps(baseRects[i]!, baseRects[j]!, gap)) {
                ignoredPairs.add(pairKey(items[i]!, items[j]!));
            }
        }
    }

    for (const request of requests) {
        const source = nodeItems.get(request.sourceId);
        if (!source) {
            continue;
        }
        items.push({
            kind: "embedded",
            key: `e${request.key}`,
            sourceId: request.sourceId,
            x: direction === "right" ? source.x + source.width + gap : source.x,
            y: direction === "right" ? source.y : source.y + source.height + gap,
            width: request.width,
            height: request.height,
        });
    }

    // Edges that flow along the push axis keep their original spacing, so a pushed step
    // carries its downstream steps along instead of squeezing into them.
    const flowingEdges = edges.flatMap((edge) => {
        const from = nodeItems.get(edge.from);
        const to = nodeItems.get(edge.to);
        if (from && to && from[axis] + from[extent] <= to[axis]) {
            return [{ from, to, spacing: to[axis] - from[axis] }];
        }
        return [];
    });

    const pushTo = (item: Item, value: number) => {
        if (value > item[axis]) {
            item[axis] = value;
            return true;
        }
        return false;
    };

    for (let iteration = 0; iteration < maxIterations; iteration++) {
        let changed = false;

        for (const item of items) {
            if (item.kind === "embedded") {
                const source = nodeItems.get(item.sourceId!)!;
                const anchored =
                    direction === "right"
                        ? { x: source.x + source.width + gap, y: source.y }
                        : { x: source.x, y: source.y + source.height + gap };
                // follow the source if it was pushed
                changed = pushTo(item, anchored[axis]) || changed;
                const cross = axis === "x" ? "y" : "x";
                item[cross] = anchored[cross];
            }
        }

        for (const { from, to, spacing } of flowingEdges) {
            changed = pushTo(to, from[axis] + spacing) || changed;
        }

        const kindOrder = (item: Item) => (item.kind === "embedded" ? 0 : 1);
        const sorted = [...items].sort((a, b) => a[axis] - b[axis] || kindOrder(a) - kindOrder(b));
        for (let i = 0; i < sorted.length; i++) {
            for (let j = i + 1; j < sorted.length; j++) {
                const a = sorted[i]!;
                const b = sorted[j]!;
                if (ignoredPairs.has(pairKey(a, b)) || !overlaps(a, b, gap)) {
                    continue;
                }
                // an embedded node is never pushed off its source by its own source
                if (b.kind === "embedded" && b.sourceId !== undefined && a.key === `n${b.sourceId}`) {
                    continue;
                }
                // embedded nodes keep their spot next to the source; push the other node
                const [fixed, moved] =
                    a.kind === "node" && b.kind === "embedded" && a[axis] >= b[axis] ? [b, a] : [a, b];
                changed = pushTo(moved, fixed[axis] + fixed[extent] + gap) || changed;
            }
        }

        if (!changed) {
            break;
        }
    }

    const result: EmbeddedLayoutResult = { nodes: {}, embedded: {}, maxDisplacement: 0, movedNodeIds: [] };
    for (const item of items) {
        const rect = { x: item.x, y: item.y, width: item.width, height: item.height };
        if (item.kind === "node") {
            const id = Number(item.key.slice(1));
            const original = nodes.find((node) => node.id === id)!;
            const displacement = Math.abs(rect.x - original.x) + Math.abs(rect.y - original.y);
            result.nodes[id] = rect;
            if (displacement > 0) {
                result.movedNodeIds.push(id);
            }
            result.maxDisplacement = Math.max(result.maxDisplacement, displacement);
        } else {
            result.embedded[item.key.slice(1)] = rect;
        }
    }
    return result;
}
