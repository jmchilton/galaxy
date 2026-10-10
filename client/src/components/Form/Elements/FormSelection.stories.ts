import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { expectOptions, pickOption } from "@tests/test-data/multiselect";
import { withModel } from "@tests/test-data/withModel";
import { h } from "vue";

import FormSelection from "./FormSelection.vue";

export const FormSelectionWithModel = withModel(FormSelection, "FormSelectionWithModel");

const meta = {
    title: "Form/Elements/FormSelection",
    component: FormSelection,
    excludeStories: ["FormSelectionWithModel"],
    render: (args) => () => h(FormSelectionWithModel, args),
    args: {
        // Tool forms pass options as [label, value]; values may be an empty string or a number.
        options: [
            ["Human (hg38)", "hg38"],
            ["Mouse (mm10)", "mm10"],
            ["Unspecified", ""],
            ["Custom build 99", 99],
        ],
    },
} satisfies Meta<typeof FormSelection>;

export default meta;
type Story = StoryObj<typeof meta>;

/** A required select with no value picks its first option. */
export const Required: Story = {};

export const Optional: Story = { args: { optional: true } };

export const OptionalSelected: Story = { args: { optional: true, value: "hg38" } };

export const MultipleRequired: Story = { args: { multiple: true, value: ["hg38"] } };

export const MultipleOptional: Story = { args: { multiple: true, optional: true, value: ["hg38", "", 99] } };

// The option labels, in order.
const OPTION_LABELS = ["Human (hg38)", "Mouse (mm10)", "Unspecified", "Custom build 99"];

/** A required select lists its options in order, with the first one picked for it. */
export const ListsOptionsInOrder: Story = {
    play: async (context) => {
        await context.step("Open the list: every option in order, the first one selected", async () => {
            await expectOptions(context, OPTION_LABELS, ["Human (hg38)"]);
        });
    },
};

/** An optional select with no value offers "Nothing selected" first, and shows it selected. */
export const OffersNothingSelected: Story = {
    args: { optional: true },
    play: async (context) => {
        await context.step('Open the list: "Nothing selected" first and selected, then every option', async () => {
            await expectOptions(context, ["Nothing selected", ...OPTION_LABELS], ["Nothing selected"]);
        });
    },
};

/** Picking "Nothing selected" clears an optional select. */
export const ClearsByPickingNothing: Story = {
    args: { optional: true, value: "hg38" },
    play: async (context) => {
        await context.step("Open the list: the saved option is selected", async () => {
            await expectOptions(context, ["Nothing selected", ...OPTION_LABELS], ["Human (hg38)"]);
        });
        await context.step('Pick "Nothing selected"; reopen the list to see it selected', async () => {
            await pickOption(context, "Nothing selected");
            await expectOptions(context, ["Nothing selected", ...OPTION_LABELS], ["Nothing selected"]);
        });
    },
};

/** Deselecting the only option of a required multi-select leaves it empty. */
export const ClearsRequiredMultiple: Story = {
    args: { multiple: true, value: ["hg38"] },
    play: async (context) => {
        await context.step("Open the list: every option in order, the saved one selected", async () => {
            await expectOptions(context, OPTION_LABELS, ["Human (hg38)"]);
        });
        await context.step("Deselect it; nothing is selected", async () => {
            await pickOption(context, "Human (hg38)");
            await expectOptions(context, OPTION_LABELS, []);
        });
    },
};

/** An optional multi-select offers no "Nothing selected"; options toggle one at a time, down to none and back. */
export const TogglesMultipleOptions: Story = {
    args: { multiple: true, optional: true, value: ["hg38", "", 99] },
    play: async (context) => {
        await context.step('Open the list: no "Nothing selected", the three saved options selected', async () => {
            await expectOptions(context, OPTION_LABELS, ["Human (hg38)", "Unspecified", "Custom build 99"]);
        });
        await context.step("Deselect the options one at a time", async () => {
            await pickOption(context, "Human (hg38)");
            await expectOptions(context, OPTION_LABELS, ["Unspecified", "Custom build 99"]);
            await pickOption(context, "Unspecified");
            await expectOptions(context, OPTION_LABELS, ["Custom build 99"]);
            await pickOption(context, "Custom build 99");
            await expectOptions(context, OPTION_LABELS, []);
        });
        await context.step("Select one again", async () => {
            await pickOption(context, "Human (hg38)");
            await expectOptions(context, OPTION_LABELS, ["Human (hg38)"]);
        });
    },
};
