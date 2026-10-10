import type { components } from "@/api";
import { http } from "@/api/client/__mocks__/http";

type GroupResponse = components["schemas"]["GroupResponse"];

/** The groups an admin form offers to add a role, quota or user to. */
export const ADMIN_GROUPS: GroupResponse[] = [
    { id: "1cd8e2f6b131e891", name: "Bioinformatics core", url: "/api/groups/1cd8e2f6b131e891", model_class: "Group" },
    { id: "ebfb8f50c6abde6d", name: "Teaching", url: "/api/groups/ebfb8f50c6abde6d", model_class: "Group" },
];

/** Answers the admin forms' request for every group. */
export function adminGroups(groups: GroupResponse[] = ADMIN_GROUPS) {
    return http.get("/api/groups", ({ response }) => response(200).json(groups));
}
