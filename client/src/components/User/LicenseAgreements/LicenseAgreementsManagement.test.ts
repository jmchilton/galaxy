import { getLocalVue, injectTestRouter } from "@tests/vitest/helpers";
import { mount } from "@vue/test-utils";
import flushPromises from "flush-promises";
import { describe, expect, it } from "vitest";

import { HttpResponse, useServerMock } from "@/api/client/__mocks__";

import LicenseAgreementsManagement from "./LicenseAgreementsManagement.vue";

const { server, http } = useServerMock();
const localVue = getLocalVue();
const router = injectTestRouter(localVue);

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
