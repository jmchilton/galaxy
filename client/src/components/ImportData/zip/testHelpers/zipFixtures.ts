import { defineComponent, h, type PropType } from "vue";

import type { ImportableFile, IZipExplorer } from "@/composables/zipExplorer";

export const FILE_CARD_SELECTOR = ".file-card-stub";

/** Stands in for the file cards, exposing the path of the file it shows. */
export const FileCardStub = defineComponent({
    props: { file: { type: Object as PropType<ImportableFile>, required: true } },
    setup(props) {
        return () => h("div", { class: "file-card-stub", "data-path": props.file.path });
    },
});

/** Files named so that their path order matches their index. */
export function makeFiles(prefix: string, count: number): ImportableFile[] {
    return Array.from({ length: count }, (_, index) => {
        const name = `${prefix}-${String(index + 1).padStart(3, "0")}`;
        return { name, path: name, size: 1, type: "file" } as ImportableFile;
    });
}

/** Explorer with only what `getImportableFiles` reads. */
export function makeExplorer(files: ImportableFile[]) {
    return {
        entries: new Map(files.map((file) => [file.path, { type: "File", path: file.path }])),
        getFileEntryMetadata: ({ path }: { path: string }) => ({ name: path, path, size: 1 }),
    } as unknown as IZipExplorer;
}
