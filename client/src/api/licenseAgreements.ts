import { type components, GalaxyApi } from "@/api";
import type { ToolIdentifier } from "@/api/tools";
import { rethrowSimple } from "@/utils/simple-error";

export type ToolLicenseAgreement = components["schemas"]["ToolLicenseAgreementResponse"];
export type LicenseAcceptance = components["schemas"]["LicenseAcceptanceResponse"];
export type LicenseAcceptanceEvent = components["schemas"]["LicenseAcceptanceEventResponse"];
export type UserLicenseAcceptances = components["schemas"]["UserLicenseAcceptancesResponse"];
export type UnmetPrecondition = components["schemas"]["UnmetPrecondition"];

/** Error code for a submission blocked by unmet tool execution preconditions. */
export const TOOL_EXECUTION_PRECONDITION_UNMET = 403009;

/** Labels of the license agreements an error's unmet preconditions name. */
export function unmetLicenseAgreementLabels(unmet: UnmetPrecondition[] | null | undefined): string[] {
    return (unmet ?? [])
        .filter((precondition) => precondition.kind === "license_agreement")
        .flatMap((precondition) => (precondition.details?.agreements as { label: string }[] | undefined) ?? [])
        .map((agreement) => agreement.label);
}

/** An agreement declared by a workflow's tools, with the steps (through subworkflows) that declare it. */
export interface WorkflowLicenseAgreement extends ToolLicenseAgreement {
    steps: { path: number[]; tool_id: string; tool_version: string }[];
}

/** Persistently accept an agreement the tool declares, confirming the terms that were displayed. */
export async function acceptLicenseAgreement(
    toolId: string,
    toolVersion: string | undefined,
    agreement: ToolLicenseAgreement,
): Promise<LicenseAcceptance> {
    const { data, error } = await GalaxyApi().POST("/api/users/{user_id}/license_acceptances", {
        params: { path: { user_id: "current" } },
        body: {
            tool_id: toolId,
            tool_version: toolVersion,
            license_id: agreement.id,
            agreement_hash: agreement.agreement_hash,
        },
    });
    if (error) {
        rethrowSimple(error);
    }
    return data;
}

export async function fetchLicenseAcceptances(includeHistory = true): Promise<UserLicenseAcceptances> {
    const { data, error } = await GalaxyApi().GET("/api/users/{user_id}/license_acceptances", {
        params: { path: { user_id: "current" }, query: { include_history: includeHistory } },
    });
    if (error) {
        rethrowSimple(error);
    }
    return data;
}

export async function revokeLicenseAcceptance(agreementHash: string): Promise<void> {
    const { error } = await GalaxyApi().DELETE("/api/users/{user_id}/license_acceptances/{agreement_hash}", {
        params: { path: { user_id: "current", agreement_hash: agreementHash } },
    });
    if (error) {
        rethrowSimple(error);
    }
}

/** A tool of the workflow declaring ``agreement``, to record a persistent acceptance against. */
export function declaringTool(agreement: WorkflowLicenseAgreement): ToolIdentifier {
    const [step] = agreement.steps;
    return { toolId: step!.tool_id, toolVersion: step!.tool_version };
}
