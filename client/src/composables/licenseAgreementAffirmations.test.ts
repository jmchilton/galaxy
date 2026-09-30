import { beforeEach, describe, expect, it, vi } from "vitest";
import { ref } from "vue";

import { acceptLicenseAgreement } from "@/api/licenseAgreements";

import { useLicenseAgreementAffirmations } from "./licenseAgreementAffirmations";

vi.mock("@/api/licenseAgreements", () => ({ acceptLicenseAgreement: vi.fn(async () => ({})) }));

function agreement(hash: string, overrides = {}) {
    return {
        agreement_hash: hash,
        id: `license_${hash}`,
        version: "1",
        label: `License ${hash}`,
        url: null,
        affirmation: "I agree.",
        terms: "Terms.",
        binds: "user" as const,
        accepted: false,
        ...overrides,
    };
}

describe("useLicenseAgreementAffirmations", () => {
    beforeEach(() => {
        vi.mocked(acceptLicenseAgreement).mockClear();
    });

    it("tracks unaffirmed agreements, ignoring accepted ones", () => {
        const agreements = ref([agreement("a"), agreement("b"), agreement("c", { accepted: true })]);
        const { affirmed, unaffirmed } = useLicenseAgreementAffirmations(agreements);
        expect(unaffirmed.value.map((a) => a.agreement_hash)).toEqual(["a", "b"]);
        affirmed.value = ["a"];
        expect(unaffirmed.value.map((a) => a.agreement_hash)).toEqual(["b"]);
    });

    it("sends affirmed agreements one-time unless remembered", () => {
        const agreements = ref([agreement("a"), agreement("b")]);
        const { affirmed, remembered, oneTimeHashes } = useLicenseAgreementAffirmations(agreements);
        affirmed.value = ["a", "b", "undeclared"];
        remembered.value = ["b"];
        expect(oneTimeHashes.value).toEqual(["a"]);
    });

    it("accepts remembered agreements against the tool that declares each", async () => {
        const agreements = ref([agreement("a"), agreement("b")]);
        const { affirmed, remembered, acceptRemembered } = useLicenseAgreementAffirmations(agreements);
        affirmed.value = ["a", "b"];
        remembered.value = ["b"];
        await acceptRemembered((declared) => ({ toolId: `tool_for_${declared.agreement_hash}`, toolVersion: "1.0" }));
        expect(acceptLicenseAgreement).toHaveBeenCalledTimes(1);
        expect(acceptLicenseAgreement).toHaveBeenCalledWith("tool_for_b", "1.0", agreements.value[1]);
    });

    it("resets affirmations", () => {
        const { affirmed, remembered, reset } = useLicenseAgreementAffirmations(ref([agreement("a")]));
        affirmed.value = ["a"];
        remembered.value = ["a"];
        reset();
        expect([affirmed.value, remembered.value]).toEqual([[], []]);
    });
});
