import type { DataOption } from "./types";
import { BATCH, SOURCE, type VariantInterface } from "./variants";

/** Help terms explaining how a data input is processed */
export const PROCESSING_HELP_TERMS = {
    mapOver: "galaxy.collections.mapOver",
    reduction: "galaxy.collections.reduction",
    nestToMapOver: "galaxy.collections.nestToMapOver",
};

/** Map-over type the server assigns when a `paired_or_unpaired` input is fed a plain list */
const SINGLE_DATASETS = "single_datasets";

export type ProcessingSource = "datasets" | "collection";

/** The tool runs once per selected dataset or once per element of the selected collection */
export interface BatchProcessingMode {
    kind: "batch";
    source: ProcessingSource;
    /** Collection type handed to each job; undefined when each job receives a single dataset */
    mapOverType?: string;
    /** Type of the selected collection, when known */
    collectionType?: string;
}

/** The input consumes the whole selection in a single job */
export interface BulkProcessingMode {
    kind: "bulk";
    source: ProcessingSource;
    /** Whether a nested collection could be mapped over this input to get one job per element */
    canNest: boolean;
}

export type ProcessingMode = BatchProcessingMode | BulkProcessingMode;

/**
 * Describe how a data input processes its selection. Batch detection mirrors
 * the `batch` flag `FormData` submits: a batch variant, or a selected
 * collection the server flagged with a `map_over_type`.
 */
export function getProcessingMode(
    variant: VariantInterface | null | undefined,
    type: "data" | "data_collection",
    values: DataOption[],
    collectionTypes: string[] = [],
): ProcessingMode | null {
    if (!variant) {
        return null;
    }
    const source: ProcessingSource = variant.src === SOURCE.DATASET ? "datasets" : "collection";
    const mapped = values.find((v) => !!v.map_over_type);
    if (variant.batch !== BATCH.DISABLED || mapped) {
        const mode: BatchProcessingMode = { kind: "batch", source };
        if (mapped && mapped.map_over_type !== SINGLE_DATASETS) {
            mode.mapOverType = mapped.map_over_type;
        }
        if (source === "collection" && values.length === 1) {
            mode.collectionType = values[0]?.collection_type;
        }
        return mode;
    }
    if (variant.multiple || type === "data_collection") {
        const canNest =
            type === "data" || collectionTypes.length === 0 || collectionTypes.some((t) => t.startsWith("list"));
        return { kind: "bulk", source, canNest };
    }
    return null;
}
