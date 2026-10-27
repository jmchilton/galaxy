import { computed, onScopeDispose, type Ref, ref, watch } from "vue";

import type { ComparisonResult, ComparisonTable } from "@/api/comparisons";
import { useUserLocalStorage } from "@/composables/userLocalStorage";
import { errorMessageAsString } from "@/utils/simple-error";

import { type CellDisplay, META_FIELDS } from "./comparisonUtils";

/** Fetches a comparison page whenever the params change; only the latest request's result is kept. */
export function useComparisonFetch<P>(
    params: Ref<P | undefined>,
    fetcher: (params: P, signal: AbortSignal) => Promise<ComparisonResult>,
    table: Ref<ComparisonTable | undefined> = ref(),
) {
    const total = ref(0);
    const loading = ref(false);
    const error = ref<string>();
    let controller: AbortController | undefined;
    let lastParams: string | undefined;

    async function load(force = false) {
        const current = params.value;
        const serialized = JSON.stringify(current);
        if (current === undefined || (!force && serialized === lastParams)) {
            return;
        }
        lastParams = serialized;
        controller?.abort();
        const own = new AbortController();
        controller = own;
        loading.value = true;
        error.value = undefined;
        try {
            const result = await fetcher(current, own.signal);
            if (controller === own) {
                table.value = result.table;
                total.value = result.total;
            }
        } catch (e) {
            if (controller === own) {
                error.value = errorMessageAsString(e, "Failed to load runs.");
            }
        } finally {
            if (controller === own) {
                loading.value = false;
            }
        }
    }

    watch(params, () => load(), { immediate: true, deep: true });
    onScopeDispose(() => controller?.abort());

    return { table, total, loading, error, reload: () => load(true) };
}

interface DisplayPrefs {
    transpose?: boolean;
    columnDisplay?: Record<string, CellDisplay>;
    hidden?: string[];
}

/** Transpose, cell displays and hidden columns, remembered per `storageKey` in local storage. */
export function useComparisonDisplay(storageKey: Ref<string | undefined>, table: Ref<ComparisonTable | undefined>) {
    const stored = useUserLocalStorage<Record<string, DisplayPrefs>>("comparison-display", {});
    const unsaved = ref<DisplayPrefs>({});

    const prefs = computed<DisplayPrefs>(() =>
        storageKey.value ? (stored.value[storageKey.value] ?? {}) : unsaved.value,
    );

    function update(patch: DisplayPrefs) {
        const next = { ...prefs.value, ...patch };
        if (storageKey.value) {
            stored.value = { ...stored.value, [storageKey.value]: next };
        } else {
            unsaved.value = next;
        }
    }

    const transpose = computed({
        get: () => Boolean(prefs.value.transpose),
        set: (value: boolean) => update({ transpose: value }),
    });
    const columnDisplay = computed({
        get: () => prefs.value.columnDisplay ?? {},
        set: (value: Record<string, CellDisplay>) => update({ columnDisplay: value }),
    });

    const allColumns = computed(() =>
        table.value
            ? [...META_FIELDS[table.value.query.kind].slice(1), ...table.value.columns.map((column) => column.key)]
            : [],
    );
    const visibleColumns = computed(() => {
        const hidden = new Set(prefs.value.hidden ?? []);
        return allColumns.value.filter((key) => !hidden.has(key));
    });

    function toggleColumn(key: string) {
        const hidden = new Set(prefs.value.hidden ?? []);
        if (hidden.has(key)) {
            hidden.delete(key);
        } else {
            hidden.add(key);
        }
        update({ hidden: [...hidden] });
    }

    function resetColumns() {
        update({ hidden: [] });
    }

    return { transpose, columnDisplay, visibleColumns, toggleColumn, resetColumns };
}
