import { type Component, defineComponent, h, type PropType, shallowRef, watch } from "vue";

import type { HDASummary } from "@/api";
import { http } from "@/api/client/__mocks__/http";
import { typesAndMappingHandler } from "@/components/Datatypes/test_fixtures";

import GButton from "@/components/BaseComponents/GButton.vue";

/** Requests every collection creator makes: its upload tab loads genomes and the datatypes mapper. */
export const collectionCreatorHandlers = {
    genomes: http.get("/api/genomes", ({ response }) => response(200).json([])),
    typesAndMapping: typesAndMappingHandler,
};

/**
 * Plays the history that feeds a collection creator its `initialElements`. Each dataset gets
 * buttons that change the history as a poll would report it: deleted, or failed. "Refresh
 * history" reports the same datasets again as new objects. Other attributes pass to the creator.
 */
export const CreatorWithHistory = defineComponent({
    name: "CreatorWithHistory",
    compatConfig: { MODE: 3 },
    inheritAttrs: false,
    props: {
        creator: { type: Object as PropType<Component>, required: true },
        history: { type: Array as PropType<HDASummary[]>, required: true },
    },
    setup(props, { attrs }) {
        const datasets = shallowRef(props.history);
        watch(
            () => props.history,
            (history) => (datasets.value = history),
        );

        function control(label: string, change: () => HDASummary[]) {
            return h(GButton, { size: "small", onClick: () => (datasets.value = change()) }, () => label);
        }

        return () =>
            h("div", [
                h(props.creator, { ...attrs, initialElements: datasets.value }),
                h("fieldset", { class: "mt-3" }, [
                    h("legend", "History"),
                    control("Refresh history", () => datasets.value.map((dataset) => ({ ...dataset }))),
                    ...datasets.value.flatMap((dataset) => [
                        control(`Delete ${dataset.name}`, () => datasets.value.filter((d) => d.id !== dataset.id)),
                        control(`Fail ${dataset.name}`, () =>
                            datasets.value.map((d) => (d.id === dataset.id ? { ...d, state: "error" as const } : d)),
                        ),
                    ]),
                ]),
            ]);
    },
});
