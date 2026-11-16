import { computed, type Ref } from "vue";

/** Text model for a filter menu `GFormInput`: the filters dict also types its values as boolean, the input holds text. */
export function useFilterText(value: Ref<string | boolean | undefined>) {
    return computed({
        get: () => (typeof value.value === "boolean" ? String(value.value) : value.value),
        set: (text: string | null | undefined) => {
            value.value = text ?? undefined;
        },
    });
}
