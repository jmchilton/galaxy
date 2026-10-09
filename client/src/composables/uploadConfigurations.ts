import { storeToRefs } from "pinia";
import { computed, ref, watch } from "vue";

import { DEFAULT_EXTENSION, getUploadDbKeys } from "@/components/Upload/utils";
import { type ExtensionDetails, useUploadDatatypes } from "@/composables/datatypes";
import type { DbKey } from "@/composables/dbKeys";
import { Toast } from "@/composables/toast";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import { errorMessageAsString } from "@/utils/simple-error";

import { useConfig } from "./config";

export type UploadConfigurations = {
    chunkUploadSize: number;
    fileSourcesConfigured: boolean;
    ftpUploadSite?: string;
    defaultDbKey: string;
    defaultExtension: string;
};

export function useUploadConfigurations(extensions: string[] | undefined) {
    const { config, isConfigLoaded } = useConfig();

    extensions = extensions?.filter((ext) => ext !== "data");

    const configOptions = computed<UploadConfigurations | null>(() =>
        isConfigLoaded.value
            ? {
                  chunkUploadSize: config.value.chunk_upload_size as number,
                  fileSourcesConfigured: config.value.file_sources_configured as boolean,
                  ftpUploadSite: (config.value.ftp_upload_site as string) || undefined,
                  defaultDbKey: (config.value.default_genome as string) || "",
                  defaultExtension: extensions?.length
                      ? extensions[0]!
                      : (config.value.default_extension as string) || DEFAULT_EXTENSION,
              }
            : null,
    );

    const { datatypes: listExtensions, loading: extensionsLoading, error: extensionsError } = useUploadDatatypes();
    const extensionsSet = computed(() => !extensionsLoading.value && !extensionsError.value);
    watch(extensionsError, (error) => {
        if (error) {
            Toast.error(error, "Unable to load upload formats");
        }
    });

    const datatypesMapperStore = useDatatypesMapperStore();
    const { datatypesMapper, loading: datatypesMapperLoading } = storeToRefs(datatypesMapperStore);
    datatypesMapperStore.createMapper().catch((error) => {
        Toast.error(errorMessageAsString(error), "Unable to load upload datatypes");
    });

    const effectiveExtensions = computed(() => {
        if (extensions?.length && datatypesMapper.value && !datatypesMapperLoading.value) {
            const result: ExtensionDetails[] = [];
            listExtensions.value.forEach((extension) => {
                if (extension && extension.id == DEFAULT_EXTENSION) {
                    result.push(extension);
                } else if (datatypesMapper.value?.isSubTypeOfAny(extension.id, extensions!)) {
                    result.push(extension);
                }
            });
            return result;
        } else {
            return listExtensions.value;
        }
    });

    const compositeExtensions = computed(() =>
        effectiveExtensions.value.filter((ext) => ext.composite_files && ext.composite_files.length > 0),
    );

    const listDbKeys = ref<DbKey[]>([]);
    const dbKeysSet = ref(false);
    async function loadDbKeys() {
        try {
            listDbKeys.value = await getUploadDbKeys(config.value?.default_genome || "");
            dbKeysSet.value = true;
        } catch (error) {
            Toast.error(errorMessageAsString(error), "Unable to load upload genomes");
        }
    }

    watch(
        () => config.value,
        async (c) => {
            if (c) {
                await loadDbKeys();
            }
        },
        { immediate: true },
    );

    const ready = computed(
        () => dbKeysSet.value && extensionsSet.value && !!datatypesMapper.value && !datatypesMapperLoading.value,
    );

    return {
        configOptions,
        effectiveExtensions,
        compositeExtensions,
        listDbKeys,
        ready,
    };
}
