import { composeStories } from "@storybook/vue3-vite";
import { useStoryMount } from "@tests/vitest/stories";
import flushPromises from "flush-promises";
import { describe, expect, it } from "vitest";

import * as InstallationSettingsStories from "./InstallationSettings.stories";

const { WithToolPanel } = composeStories(InstallationSettingsStories);
const mountStory = useStoryMount();

async function mountInstallationSettings() {
    const wrapper = mountStory(WithToolPanel);
    await flushPromises();
    return wrapper;
}

/** Each dependency checkbox's label, mapped to whether it is checked. */
function dependencyOptions(wrapper) {
    return Object.fromEntries(
        wrapper
            .findAll(".custom-checkbox")
            .map((option) => [option.find("label").text(), option.find("input").element.checked]),
    );
}

describe("InstallationSettings", () => {
    it("titles the dialog with the repository and shows its long description, owner and revision", async () => {
        const wrapper = await mountInstallationSettings();
        const { repo, changesetRevision } = WithToolPanel.args;

        expect(wrapper.find(".g-modal-title").text()).toBe(`Installing '${repo.name}'`);
        expect(wrapper.find(".description").text()).toBe(repo.long_description);
        expect(wrapper.find(".revision").text()).toBe(`${repo.owner} rev. ${changesetRevision}`);
    });

    it("checks each dependency option the server configuration enables", async () => {
        const wrapper = await mountInstallationSettings();

        expect(dependencyOptions(wrapper)).toEqual({
            "Install resolvable dependencies": true,
            "Install repository dependencies": true,
            "Install tool dependencies": true,
        });
    });
});
