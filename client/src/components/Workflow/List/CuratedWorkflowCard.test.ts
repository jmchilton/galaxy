import { composeStories } from "@storybook/vue3-vite";
import { deferred } from "@tests/vitest/deferred";
import { createTestRouter } from "@tests/vitest/helpers";
import { type StoryOf, useStoryMount } from "@tests/vitest/stories";
import flushPromises from "flush-promises";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import type { CuratedWorkflow } from "@/api/curatedWorkflows";
import { Services } from "@/components/Workflow/services";
import { copyWorkflow } from "@/components/Workflow/workflows.services";
import { Toast } from "@/composables/toast";
import { ensureDefined } from "@/utils/assertions";

import * as CuratedWorkflowCardStories from "./CuratedWorkflowCard.stories";

import CuratedWorkflowCard from "./CuratedWorkflowCard.vue";
import GCard from "@/components/Common/GCard.vue";

// Spied, not replaced: imports still reach the story's handlers.
const importTrsToolFromUrl = vi.spyOn(Services.prototype, "importTrsToolFromUrl");
vi.mock("@/components/Workflow/workflows.services", { spy: true });

vi.mock("@/components/Workflow/redirectPath", () => ({
    getRedirectOnImportPath: () => "/workflows/list",
}));

const stories = composeStories(CuratedWorkflowCardStories);
const mountStory = useStoryMount();

const toastError = vi.spyOn(Toast, "error");
let routerPush: ReturnType<typeof vi.spyOn>;

const CATALOG_WORKFLOW = ensureDefined(stories.CatalogWorkflow.args.workflow);
const PINNED_TRS_URL = CATALOG_WORKFLOW.trs_url;
const BRANCH_TRS_URL = CATALOG_WORKFLOW.trs_fallback_url;

type CardStory = StoryOf<typeof stories>;

function mountCard(story: CardStory) {
    const router = createTestRouter();
    // Stubbed so the assertions can see navigation; a real push would also
    // warn about redundant routes across repeated mounts.
    routerPush = vi.spyOn(router, "push").mockResolvedValue(undefined);
    return mountStory(story, { router });
}

function workflowOf(story: CardStory): CuratedWorkflow {
    return ensureDefined(story.args.workflow);
}

function importActionOf(wrapper: ReturnType<typeof mountCard>) {
    const action = ensureDefined(
        ensureDefined(wrapper.getComponent(GCard).props("primaryActions")).find(
            (action) => action.id === "curated-import",
        ),
    );
    return { ...action, handler: ensureDefined(action.handler) };
}

async function clickImport(wrapper: ReturnType<typeof mountCard>, workflow: CuratedWorkflow) {
    await wrapper.get(`#g-card-action-curated-import-${workflow.id}`).trigger("click");
    await flushPromises();
}

function badgeById(wrapper: ReturnType<typeof mountCard>, id: string) {
    const badges = wrapper.getComponent(GCard).props("badges") ?? [];
    return badges.find((badge) => badge.id === id);
}

function requiredBadgeById(wrapper: ReturnType<typeof mountCard>, id: string) {
    const badge = badgeById(wrapper, id);
    if (!badge) {
        throw new Error(`No badge "${id}" on the card`);
    }
    return badge;
}

function actionIds(wrapper: ReturnType<typeof mountCard>): string[] {
    const card = wrapper.getComponent(GCard);
    const actions = [...(card.props("primaryActions") ?? []), ...(card.props("extraActions") ?? [])];
    return actions.map((action) => action.id);
}

describe("CuratedWorkflowCard", () => {
    beforeEach(() => {
        importTrsToolFromUrl.mockReset();
        vi.mocked(copyWorkflow).mockReset();
        toastError.mockClear();
    });

    it("renders the title as plain text with no preview link", () => {
        // A catalog row's id is an IWC slug, so a preview modal keyed on it would 404.
        const wrapper = mountCard(stories.CatalogWorkflow);
        const title = wrapper.get(`#g-card-title-${CATALOG_WORKFLOW.id}`);

        expect(title.text()).toContain("Velocyto on 10x filtered barcodes");
        expect(wrapper.find(`#g-card-title-link-${CATALOG_WORKFLOW.id}`).exists()).toBe(false);
        expect(title.find("a").exists()).toBe(false);
    });

    it("marks the card so Selenium's workflow-card count is unaffected", () => {
        const card = mountCard(stories.CatalogWorkflow).getComponent(CuratedWorkflowCard);

        expect(card.classes()).toContain("curated-workflow-card");
        expect(card.classes()).not.toContain("workflow-card");
    });

    it("offers import and external links for a catalog row", () => {
        const ids = actionIds(mountCard(stories.CatalogWorkflow));

        expect(ids).toContain("curated-import");
        expect(ids).toContain("curated-external-link");
        expect(ids).toContain("curated-doi");
        expect(ids).not.toContain("curated-run");
    });

    it("offers run and view for a workflow hosted on this Galaxy", () => {
        const ids = actionIds(mountCard(stories.HostedHere));

        expect(ids).toContain("curated-run");
        expect(ids).toContain("curated-import");
        expect(ids).toContain("curated-open");
        expect(ids).not.toContain("curated-external-link");
    });

    it("enables import for a registered user", () => {
        // Without this the handler tests below would still pass if the action
        // were disabled and therefore unclickable.
        const importAction = importActionOf(mountCard(stories.CatalogWorkflow));

        expect(importAction.disabled).toBe(false);
    });

    it("disables import for a catalog row with no TRS URL to import", () => {
        const importAction = importActionOf(mountCard(stories.NotImportable));

        expect(importAction.disabled).toBe(true);
    });

    it("disables import for anonymous users", () => {
        const importAction = importActionOf(mountCard(stories.Anonymous));

        expect(importAction.disabled).toBe(true);
        expect(importAction.title).toBe("Log in to import this workflow");
    });

    it("imports a catalog row through TRS with the values the server supplied", async () => {
        const wrapper = mountCard(stories.CatalogWorkflow);

        await clickImport(wrapper, CATALOG_WORKFLOW);

        expect(importTrsToolFromUrl).toHaveBeenCalledTimes(1);
        expect(importTrsToolFromUrl).toHaveBeenCalledWith(PINNED_TRS_URL);
        expect(copyWorkflow).not.toHaveBeenCalled();
        // Without this the test passes even when the import throws and is swallowed.
        expect(routerPush).toHaveBeenCalledWith("/workflows/list");
        expect(toastError).not.toHaveBeenCalled();
    });

    it("surfaces a failed TRS import instead of navigating", async () => {
        const wrapper = mountCard(stories.DockstoreUnreachable);

        await clickImport(wrapper, workflowOf(stories.DockstoreUnreachable));

        // Only a missing release falls back; any other failure is reported as is.
        expect(importTrsToolFromUrl).toHaveBeenCalledTimes(1);
        expect(routerPush).not.toHaveBeenCalled();
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining("could not be reached"));
    });

    it("falls back to the branch when the release is not on the TRS server yet", async () => {
        const wrapper = mountCard(stories.ReleaseNotOnDockstoreYet);

        await clickImport(wrapper, workflowOf(stories.ReleaseNotOnDockstoreYet));

        expect(importTrsToolFromUrl.mock.calls).toEqual([[PINNED_TRS_URL], [BRANCH_TRS_URL]]);
        expect(routerPush).toHaveBeenCalledWith("/workflows/list");
        expect(toastError).not.toHaveBeenCalled();
    });

    it("reports a missing release when there is no branch to fall back to", async () => {
        const wrapper = mountCard(stories.NotOnDockstore);

        await clickImport(wrapper, workflowOf(stories.NotOnDockstore));

        expect(importTrsToolFromUrl).toHaveBeenCalledTimes(1);
        expect(routerPush).not.toHaveBeenCalled();
        expect(toastError).toHaveBeenCalledWith(expect.stringContaining("responded with HTTP 404"));
    });

    it("asks to filter by a collection when its badge is clicked", async () => {
        const wrapper = mountCard(stories.CatalogWorkflow);

        const badge = wrapper.get("[id^='g-card-badge-curated-collection-']");
        expect(badge.text()).toContain("Single Cell");
        await badge.trigger("click");

        expect(wrapper.getComponent(CuratedWorkflowCard).emitted("collectionClick")).toEqual([["Single Cell"]]);
    });

    it("says a workflow is ready to run when nothing is missing", () => {
        const wrapper = mountCard(stories.CatalogWorkflow);

        expect(badgeById(wrapper, "curated-runnable")).toMatchObject({ label: "Ready to run", variant: "success" });
        expect(badgeById(wrapper, "curated-missing-tools")).toBeUndefined();
    });

    it("counts the missing tools and names them by their short id", () => {
        const wrapper = mountCard(stories.NeedsTools);
        const badge = requiredBadgeById(wrapper, "curated-missing-tools");

        expect(badge).toMatchObject({ label: "Needs 3 tools", variant: "warning" });
        expect(badge.title).toBe("Not installed on this Galaxy: fastp, multiqc, wig_to_bigWig");
        expect(badgeById(wrapper, "curated-runnable")).toBeUndefined();
    });

    it("keeps import enabled when tools are missing, so an admin can import and install them", () => {
        const wrapper = mountCard(stories.NeedsOneTool);

        expect(requiredBadgeById(wrapper, "curated-missing-tools").label).toBe("Needs 1 tool");
        expect(importActionOf(wrapper).disabled).toBe(false);
    });

    it("shows no runnability badge when the server did not check", () => {
        const wrapper = mountCard(stories.HostedHere);

        expect(badgeById(wrapper, "curated-runnable")).toBeUndefined();
        expect(badgeById(wrapper, "curated-missing-tools")).toBeUndefined();
    });

    it("copies a locally hosted workflow instead of importing it through TRS", async () => {
        const wrapper = mountCard(stories.HostedHere);

        await clickImport(wrapper, workflowOf(stories.HostedHere));

        expect(copyWorkflow).toHaveBeenCalledWith("f2db41e1fa331b3e", "curator");
        expect(importTrsToolFromUrl).not.toHaveBeenCalled();
        expect(toastError).not.toHaveBeenCalled();
    });

    it.each([
        ["catalog", stories.CatalogWorkflow, importTrsToolFromUrl],
        ["local", stories.HostedHere, vi.mocked(copyWorkflow)],
    ])("ignores repeat clicks while a %s import is in flight", async (_kind, story, importCall) => {
        const pending = deferred<unknown>();
        importCall.mockReturnValue(pending.promise as never);
        const wrapper = mountCard(story);
        onTestFinished(async () => {
            pending.resolve({ id: "abc123", message: "Imported", status: "success" });
            await flushPromises();
        });
        const importAction = () => importActionOf(wrapper);

        const first = importAction().handler();
        await wrapper.vm.$nextTick();
        expect(importAction().disabled).toBe(true);
        await importAction().handler();
        expect(importCall).toHaveBeenCalledTimes(1);

        pending.resolve({ id: "abc123", message: "Imported", status: "success" });
        await first;
        await flushPromises();
        expect(importAction().disabled).toBe(false);
    });
});
