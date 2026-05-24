import type { GraphNode } from "@/components/Graph/types";

// State colors resolved lazily from the global `--state-color-*` custom
// properties defined in base.scss.
const stateColors: Record<string, string> = {};

function stateColor(state: string): string {
    if (!(state in stateColors)) {
        stateColors[state] = getComputedStyle(document.documentElement)
            .getPropertyValue(`--state-color-${state.replace(/_/g, "-")}`)
            .trim();
    }
    return stateColors[state]!;
}

/**
 * Minimap fill color for a history graph node. Dataset/collection nodes use
 * their state color; tool nodes return null so the minimap applies its default.
 */
export function historyNodeColor(node: GraphNode): string | null {
    if ((node.data?.src as string) === "tool_request") {
        return null;
    }
    const state = node.data?.state as string | undefined;
    return (state && stateColor(state)) || null;
}

let brandPrimary: string | null = null;
function getBrandPrimary(): string {
    if (brandPrimary === null) {
        brandPrimary = getComputedStyle(document.documentElement).getPropertyValue("--brand-primary").trim();
    }
    return brandPrimary;
}

/**
 * Background + text color for the Information tab title, matching what the
 * node header shows in the graph. Returns null when no meaningful color
 * applies (defaults to the regular tab look).
 */
export function nodeHeaderColor(node: GraphNode): { backgroundColor: string; color?: string } | null {
    if ((node.data?.src as string) === "tool_request") {
        const bg = getBrandPrimary();
        return bg ? { backgroundColor: bg, color: "white" } : null;
    }
    const bg = historyNodeColor(node);
    return bg ? { backgroundColor: bg } : null;
}
