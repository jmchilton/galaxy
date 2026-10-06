import "ag-grid-community/styles/ag-grid.min.css";
import "ag-grid-community/styles/ag-theme-alpine.min.css";

import type { GridApi, GridReadyEvent } from "ag-grid-community";
import { defineAsyncComponent, nextTick, shallowRef } from "vue";

// ag-grid-vue3 is a Vue 3 component; under the app's MODE 2 compat its `v-model` would be rewritten to
// `value`/`input`. Compat checks each vnode's own component, so both the async wrapper and the grid opt out.
const VUE3_MODE = { compatConfig: { MODE: 3 as const } };
const AgGridVue = Object.assign(
    defineAsyncComponent(async () => {
        const [{ AgGridVue }, { AllCommunityModule, enableDevValidations, ModuleRegistry, provideGlobalGridOptions }] =
            await Promise.all([import("ag-grid-vue3"), import("ag-grid-community")]);
        ModuleRegistry.registerModules([AllCommunityModule]);
        if (process.env.NODE_ENV === "development") {
            enableDevValidations();
        }
        // Keep the CSS file themes imported above (and the `ag-theme-alpine` wrapper class), not the Theming API,
        // and 30's unanimated rows (removed rows linger in the DOM while animating out).
        provideGlobalGridOptions({ theme: "legacy", animateRows: false });
        return { ...AgGridVue, ...VUE3_MODE } as unknown as typeof AgGridVue;
    }),
    VUE3_MODE,
);

/** `forceGridSize` defaults to fitting the columns to the grid's width. */
export function useAgGrid(forceGridSize?: () => void) {
    const gridApi = shallowRef<GridApi | null>(null);
    const theme = "ag-theme-alpine";

    const resize = forceGridSize ?? (() => gridApi.value?.sizeColumnsToFit());

    function resizeOnNextTick() {
        nextTick(resize);
    }

    function onGridReady(params: GridReadyEvent) {
        gridApi.value = params.api;
        resize();
    }

    return { AgGridVue, gridApi, resize, resizeOnNextTick, onGridReady, theme };
}
