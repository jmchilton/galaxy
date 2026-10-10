import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { type Component, defineComponent, h, ref } from "vue";

import FormSelection from "./FormSelection.vue";

/** Plays the parent's part of v-model: every `input` FormSelection emits comes back as its `value`. */
export const FormSelectionWithModel = defineComponent({
    name: "FormSelectionWithModel",
    inheritAttrs: false,
    setup(_props, { attrs }) {
        const value = ref(attrs.value);
        return () =>
            h(FormSelection as Component, {
                ...attrs,
                value: value.value,
                onInput: (newValue: unknown) => {
                    value.value = newValue;
                },
            });
    },
});

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
