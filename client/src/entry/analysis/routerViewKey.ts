import type { RouteLocationNormalizedLoaded } from "vue-router";

/**
 * Key for the center router-view; a new key remounts the center component.
 *
 * Every `/galaxyai` route renders one and the same GalaxyAI instance: it rewrites its own route as a
 * conversation is created (`/galaxyai` to `/galaxyai/<id>`) or reset (`/galaxyai/new`) and follows
 * those changes through its `exchangeId` prop, so the live conversation stays in place. A route with
 * `meta.keepMountedOnQueryChange` keeps its component across query changes and follows them through
 * its props. All other routes get a fresh component per path and query.
 */
export function centerRouterViewKey(route: Pick<RouteLocationNormalizedLoaded, "path" | "fullPath" | "meta">): string {
    if (route.path.startsWith("/galaxyai")) {
        return "/galaxyai";
    }
    return route.meta.keepMountedOnQueryChange ? route.path : route.fullPath;
}
