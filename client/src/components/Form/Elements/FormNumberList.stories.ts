import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { withModel } from "@tests/test-data/withModel";
import { expect } from "storybook/test";
import { h } from "vue";

import FormNumberList from "./FormNumberList.vue";

export const FormNumberListWithModel = withModel(FormNumberList, "FormNumberListWithModel");

/**
 * A workflow's multiple-integer input on its run form, one number field per value: here the column
 * numbers a workflow passes to a tool's multiple-column parameter. The run form marks each field
 * valid or invalid.
 */
const meta = {
    title: "Form/Elements/FormNumberList",
    component: FormNumberList,
    excludeStories: ["FormNumberListWithModel"],
    render: (args) => () => h(FormNumberListWithModel, args),
    args: { id: "columns", type: "integer", showState: true },
} satisfies Meta<typeof FormNumberList>;

export default meta;
type Story = StoryObj<typeof meta>;

/** With no value there is one empty field, and it can't be removed. */
export const Unset: Story = { args: { value: null } };

/** A single value can't be removed either; clearing it unsets the input. */
export const OneColumn: Story = { args: { value: [1] } };

export const TwoColumns: Story = { args: { value: [1, 2] } };

export const AddsAndRemovesColumns: Story = {
    ...OneColumn,
    play: async ({ canvas, userEvent, step }) => {
        await step("Start with one column", async () => {
            await expect(canvas.getAllByRole("spinbutton")).toHaveLength(1);
            await expect(canvas.getByRole("spinbutton")).toHaveValue(1);
            await expect(canvas.getByRole("button", { name: "Remove value" })).toHaveAttribute("aria-disabled", "true");
        });
        await step("Add another field and enter column three", async () => {
            await userEvent.click(canvas.getByRole("button", { name: "Add value" }));
            const fields = canvas.getAllByRole("spinbutton");
            await expect(fields).toHaveLength(2);
            await expect(fields[0]).toHaveValue(1);
            await expect(fields[1]).toHaveValue(null);
            await expect(fields[1]).toHaveAttribute("aria-invalid", "true");
            await userEvent.type(fields[1]!, "3");
            await expect(fields[1]).toHaveValue(3);
            await expect(fields[1]).not.toHaveAttribute("aria-invalid", "true");
        });
        await step("Remove the first column and keep the entered value", async () => {
            await userEvent.click(canvas.getAllByRole("button", { name: "Remove value" })[0]!);
            await expect(canvas.getAllByRole("spinbutton")).toHaveLength(1);
            await expect(canvas.getByRole("spinbutton")).toHaveValue(3);
            await expect(canvas.getByRole("spinbutton")).not.toHaveAttribute("aria-invalid", "true");
            await expect(canvas.getByRole("button", { name: "Remove value" })).toHaveAttribute("aria-disabled", "true");
        });
    },
};

export const ClearsLastColumn: Story = {
    ...OneColumn,
    play: async ({ canvas, userEvent, step }) => {
        await step("Start with a valid column number", async () => {
            await expect(canvas.getByRole("spinbutton")).toHaveValue(1);
            await expect(canvas.getByRole("spinbutton")).not.toHaveAttribute("aria-invalid", "true");
        });
        await step("Clear the value while keeping an empty required field", async () => {
            await userEvent.clear(canvas.getByRole("spinbutton"));
            await expect(canvas.getAllByRole("spinbutton")).toHaveLength(1);
            await expect(canvas.getByRole("spinbutton")).toHaveValue(null);
            await expect(canvas.getByRole("spinbutton")).toHaveAttribute("aria-invalid", "true");
            await expect(canvas.getByRole("button", { name: "Remove value" })).toHaveAttribute("aria-disabled", "true");
        });
    },
};
