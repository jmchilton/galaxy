import { storeToRefs } from "pinia";
import { computed, ref } from "vue";

import type { DbKey } from "@/composables/uploadConfigurations";
import { useDbKeyStore } from "@/stores/dbKeyStore";
import { errorMessageAsString } from "@/utils/simple-error";

/**
 * Upload Database/Builds from the shared dbkey store, unspecified (`?`) first.
 * `error` holds the message when loading fails; the next caller retries.
 */
export function useUploadDbKeys() {
    const dbKeyStore = useDbKeyStore();
    const { getUploadDbKeys } = storeToRefs(dbKeyStore);
    const dbKeys = computed(() => getUploadDbKeys.value as DbKey[]);
    const loading = ref(true);
    const error = ref<string | null>(null);

    dbKeyStore
        .fetchUploadDbKeys()
        .catch((e: unknown) => {
            error.value = errorMessageAsString(e);
        })
        .finally(() => {
            loading.value = false;
        });

    return { dbKeys, loading, error };
}
