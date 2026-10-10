import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { expect, screen } from "storybook/test";

import type { ObjectStoreBadgeType } from "@/api/objectStores.templates";
import { escapeRegExp } from "@/utils/regExp";

import { MESSAGES } from "./badgeMessages";

import ObjectStoreBadges from "./ObjectStoreBadges.vue";

const badges: ObjectStoreBadgeType[] = [
    { type: "more_secure", message: "Encrypted at rest.", source: "admin" },
    { type: "slower", message: "Backed by tape; reads can take hours.", source: "admin" },
];

const meta = {
    title: "ObjectStore/ObjectStoreBadges",
    component: ObjectStoreBadges,
    args: { badges },
} satisfies Meta<typeof ObjectStoreBadges>;

export default meta;
type Story = StoryObj<typeof meta>;
type PlayContext = Parameters<NonNullable<Story["play"]>>[0];

/** The stock explanation of the badge's type, then the admin's own note if it has one. */
function describes({ type, message }: ObjectStoreBadgeType) {
    const note = message ? `\\s.*${escapeRegExp(message)}` : "";
    return new RegExp(`^${escapeRegExp(MESSAGES[type])}${note}`, "s");
}

/** Every badge is shown, in order, and explained on hover. */
async function seeBadges({ canvas, userEvent, step }: PlayContext) {
    // The badges are icons, so their tooltip text is the only name they have.
    const shown = canvas.getAllByLabelText(/./);
    await step("See one badge per storage property, each named by its explanation", async () => {
        await expect(shown.map((badge) => badge.getAttribute("aria-label"))).toEqual(
            badges.map((badge) => expect.stringMatching(describes(badge))),
        );
    });
    for (const [index, badge] of badges.entries()) {
        await step(`Hover the ${badge.type} badge to read its explanation`, async () => {
            await userEvent.hover(shown[index]!);
            await expect(await screen.findByRole("tooltip")).toHaveTextContent(describes(badge));
            await userEvent.unhover(shown[index]!);
        });
    }
}

/** No size given, so each badge falls back to its default `lg` icon size. */
export const DefaultSize: Story = {
    play: seeBadges,
};

/** Badges drawn at twice the base icon size. */
export const DoubleSize: Story = {
    args: { size: "2x" },
    play: seeBadges,
};
