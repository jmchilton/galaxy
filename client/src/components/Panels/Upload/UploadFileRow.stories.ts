import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { getFakeHistorySummary } from "@tests/test-data";
import { withCurrentHistory } from "@tests/test-data/currentHistory";
import { expect } from "storybook/test";
import { h } from "vue";

import { makeLocalFileItem, makeUrlItem, withUploadState } from "@/composables/upload/testHelpers/uploadFixtures";

import UploadFileRow from "./UploadFileRow.vue";

const HISTORY_ID = "c4f1a2b3d5e60718";
const LINK = "https://zenodo.org/records/582600/files/mutant_R1.fastq";
const HISTORY = getFakeHistorySummary({
    id: HISTORY_ID,
    name: "Mutation calling",
    url: `/api/histories/${HISTORY_ID}`,
});

/** One upload in the upload panel's queue, headed for the current history. */
const meta = {
    title: "Panels/Upload/UploadFileRow",
    component: UploadFileRow,
    decorators: [withCurrentHistory(HISTORY)],
    // Replaces the fixture's createdAt (0, i.e. 1970) with a minute before the story renders, so the elapsed time reads as it would in the app.
    render: (args) => () => h(UploadFileRow, { ...args, file: { ...args.file, createdAt: Date.now() - 60_000 } }),
} satisfies Meta<typeof UploadFileRow>;

export default meta;
type Story = StoryObj<typeof meta>;

type PlayContext = Parameters<NonNullable<Story["play"]>>[0];

/**
 * Checks the row shows the full link in its text and tooltip, and an icon to copy it. The icon
 * shows on hover through CSS, which a play's scripted hover doesn't trigger, so it's only checked
 * present; clicking it does nothing (BUGS_FOUND), so the unit test checks what it would copy.
 */
async function seeLink({ canvas, step }: PlayContext) {
    await step('See the link and its hover-only "Copy link" icon', async () => {
        const link = canvas.getByText(LINK);
        await expect(link).toBeVisible();
        await expect(link).toHaveAttribute("title", LINK);
        await expect(copyIcon(canvas)).toBeInTheDocument();
    });
}

/**
 * The copy icon, by its `<title>`: the svg has no `aria-labelledby`, so Testing Library gives it no
 * name to find it by role. It isn't a button either, so it has no tab stop (BUGS_FOUND).
 */
function copyIcon(canvas: PlayContext["canvas"]) {
    return canvas.queryByTitle("Copy link")?.closest("svg") ?? null;
}

/** A pasted link waits its turn; the row shows the link, with a copy icon on hover. */
export const LinkQueued: Story = {
    args: {
        file: withUploadState(
            makeUrlItem({
                name: "mutant_R1.fastq",
                url: LINK,
                targetHistoryId: HISTORY_ID,
            }),
        ),
    },
    play: seeLink,
};

/** A file from the user's computer, part way through; it has no link to show and can be cancelled. */
export const FileUploading: Story = {
    args: {
        file: withUploadState(
            makeLocalFileItem({
                name: "wildtype.fna",
                size: 4_700_000,
                fileData: new File([], "wildtype.fna"),
                targetHistoryId: HISTORY_ID,
            }),
            { status: "uploading", progress: 45 },
        ),
    },
    play: async ({ canvas, step }) => {
        await step("See the file, with no link and nothing to copy", async () => {
            await expect(canvas.getByText("wildtype.fna")).toBeVisible();
            await expect(canvas.queryByText(/https?:\/\//)).not.toBeInTheDocument();
            await expect(copyIcon(canvas)).not.toBeInTheDocument();
        });
    },
};
