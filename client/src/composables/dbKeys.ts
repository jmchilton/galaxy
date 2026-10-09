import { storeToRefs } from "pinia";
import { computed } from "vue";

import type { DbKey } from "@/composables/uploadConfigurations";
import { useDbKeyStore } from "@/stores/dbKeyStore";

/**
 * Upload Database/Builds from the shared dbkey store, which owns loading and error state; unspecified (`?`) first.
 * `error` holds the message when loading fails; the next caller retries.
 */
export function useUploadDbKeys() {
    const dbKeyStore = useDbKeyStore();
    const { getUploadDbKeys, uploadDbKeysLoading, uploadDbKeysError } = storeToRefs(dbKeyStore);
    const dbKeys = computed(() => getUploadDbKeys.value as DbKey[]);

    // Failures surface through `uploadDbKeysError`.
    dbKeyStore.fetchUploadDbKeys().catch(() => {});

    return { dbKeys, loading: uploadDbKeysLoading, error: uploadDbKeysError };
}
