import { type MaybeRefOrGetter, toValue } from "@vueuse/core";
import { storeToRefs } from "pinia";
import { computed, watch } from "vue";

import { useDbKeyStore } from "@/stores/dbKeyStore";

export type DbKey = {
    id: string;
    text: string;
};

/**
 * Upload Database/Builds from the shared dbkey store, which owns loading and error state; unspecified (`?`) first.
 * `error` holds the message when loading fails; the next caller retries. Loading waits until `enabled` is true.
 */
export function useUploadDbKeys({ enabled = true }: { enabled?: MaybeRefOrGetter<boolean> } = {}) {
    const dbKeyStore = useDbKeyStore();
    const { getUploadDbKeys, uploadDbKeysLoading, uploadDbKeysError } = storeToRefs(dbKeyStore);
    const dbKeys = computed(() => getUploadDbKeys.value as DbKey[]);

    watch(
        () => toValue(enabled),
        (isEnabled) => {
            if (isEnabled) {
                // Failures surface through `uploadDbKeysError`.
                dbKeyStore.fetchUploadDbKeys().catch(() => {});
            }
        },
        { immediate: true },
    );

    return { dbKeys, loading: uploadDbKeysLoading, error: uploadDbKeysError };
}
