import { type components, GalaxyApi } from "@/api";
import { rethrowSimple } from "@/utils/simple-error";

export type ToolLicenseAgreement = components["schemas"]["ToolLicenseAgreementResponse"];
export type LicenseAcceptance = components["schemas"]["LicenseAcceptanceResponse"];
export type LicenseAcceptanceEvent = components["schemas"]["LicenseAcceptanceEventResponse"];
export type UserLicenseAcceptances = components["schemas"]["UserLicenseAcceptancesResponse"];

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
