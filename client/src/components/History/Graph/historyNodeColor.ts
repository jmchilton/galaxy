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

