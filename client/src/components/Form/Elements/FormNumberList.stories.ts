import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { withModel } from "@tests/test-data/withModel";
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
