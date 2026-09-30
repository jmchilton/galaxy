import { getLocalVue, injectTestRouter } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it, vi } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import LicenseAgreementsManagement from "./LicenseAgreementsManagement.vue";

vi.mock("@/composables/confirmDialog", () => ({
    useConfirmDialog: () => ({ confirm: () => Promise.resolve(true) }),
}));

const { server, http } = useServerMock();
const localVue = getLocalVue();
const router = injectTestRouter(localVue);

const HASH = "c".repeat(64);

function event(action: "accept" | "revoke", id: string) {
    return {
        id,
        agreement_hash: HASH,
        action,
        license_id: "test_license",
        license_version: "1",
        license_label: "Test License",
        license_url: null,
        granted_by: "user",
        prompting_tool_id: action === "accept" ? "licensed_tool" : null,
        prompting_tool_version: null,
        create_time: "2026-09-30T12:00:00",
    };
}

function acceptancesResponse(accepted: boolean) {
    return {
        accepted: accepted
            ? [
                  {
                      agreement: { agreement_hash: HASH, affirmation: "I agree.", terms: "Test terms." },
                      event: event("accept", "e1"),
                  },
              ]
            : [],
        history: accepted ? [event("accept", "e1")] : [event("accept", "e1"), event("revoke", "e2")],
    };
}

async function mountManagement() {
    const wrapper = mount(LicenseAgreementsManagement as object, {
        localVue,
        router,
        stubs: { BreadcrumbHeading: true, UtcDate: true },
    });
    await flushPromises();
    return wrapper;
}

describe("LicenseAgreementsManagement", () => {
    it("lists accepted agreements and history", async () => {
        server.use(
            http.untyped.get("/api/users/current/license_acceptances", () =>
                HttpResponse.json(acceptancesResponse(true)),
            ),
        );
        const wrapper = await mountManagement();
        expect(wrapper.find(".license-acceptance[data-license-id='test_license']").text()).toContain("Test License");
        expect(wrapper.findAll(".license-acceptance-event").length).toBe(1);
    });

    it("revokes an acceptance and reloads", async () => {
        let revoked = false;
        server.use(
            http.untyped.get("/api/users/current/license_acceptances", () =>
                HttpResponse.json(acceptancesResponse(!revoked)),
            ),
            http.untyped.delete(`/api/users/current/license_acceptances/${HASH}`, () => {
                revoked = true;
                return new HttpResponse(null, { status: 204 });
            }),
        );
        const wrapper = await mountManagement();
        await wrapper.find("[data-test-id='license-revoke-test_license']").trigger("click");
        await flushPromises();
        expect(revoked).toBe(true);
        expect(wrapper.find("[data-description='no accepted licenses']").exists()).toBe(true);
        const actions = wrapper
            .findAll(".license-acceptance-event")
            .wrappers.map((row) => row.attributes("data-action"));
        expect(actions).toEqual(["accept", "revoke"]);
    });

    it("shows loading errors", async () => {
        server.use(
            http.untyped.get("/api/users/current/license_acceptances", () =>
                HttpResponse.json({ err_msg: "Nope." }, { status: 500 }),
            ),
        );
        const wrapper = await mountManagement();
        expect(wrapper.text()).toContain("Nope.");
    });
});
