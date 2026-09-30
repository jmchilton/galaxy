import { computed, type Ref, ref } from "vue";

import { acceptLicenseAgreement, type ToolLicenseAgreement } from "@/api/licenseAgreements";

/**
 * What the user affirmed for the license agreements a submission needs.
 *
 * Affirmed agreements are sent with the submission as one-time acceptances; remembered ones
 * (``binds="user"`` only) are instead accepted persistently before submitting.
 */
export function useLicenseAgreementAffirmations(agreements: Ref<ToolLicenseAgreement[]>) {
    /** Hashes of the agreements the user has affirmed. */
    const affirmed = ref<string[]>([]);
    /** Hashes of affirmed agreements the user wants remembered. */
    const remembered = ref<string[]>([]);

    const unaffirmed = computed(() =>
        agreements.value.filter(
            (agreement) => !agreement.accepted && !affirmed.value.includes(agreement.agreement_hash),
        ),
    );

    const oneTimeHashes = computed(() =>
        agreements.value
            .map((agreement) => agreement.agreement_hash)
            .filter(
                (agreementHash) => affirmed.value.includes(agreementHash) && !remembered.value.includes(agreementHash),
            ),
    );

    /** Persistently accept the remembered agreements, so the submission is authorized by those acceptances. */
    async function acceptRemembered(toolId: string, toolVersion: string | undefined) {
        for (const agreement of agreements.value) {
            if (remembered.value.includes(agreement.agreement_hash)) {
                await acceptLicenseAgreement(toolId, toolVersion, agreement);
            }
        }
    }

    function reset() {
        affirmed.value = [];
        remembered.value = [];
    }

    return { affirmed, remembered, unaffirmed, oneTimeHashes, acceptRemembered, reset };
}
