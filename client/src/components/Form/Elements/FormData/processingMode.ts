import type { CollectionType } from "@/api/datasetCollections";
import { collectionTypeLabel } from "@/components/Collections/common/buildCollectionModal";

import type { DataOption } from "./types";
import { BATCH, SOURCE, type VariantInterface } from "./variants";

/** Help terms explaining how a data input is processed */
export const PROCESSING_HELP_TERMS = {
    mapOver: "galaxy.collections.mapOver",
    reduction: "galaxy.collections.reduction",
    nestToMapOver: "galaxy.collections.nestToMapOver",
} as const;

/** Map-over type the server assigns when a `paired_or_unpaired` input is fed a plain list */
const SINGLE_DATASETS = "single_datasets";

/** What each job receives when a collection is mapped over, e.g. "dataset pair" or "nested list:list" */
export function mapOverUnit(mapOverType?: string | null): string {
    if (!mapOverType || mapOverType === SINGLE_DATASETS) {
        return "dataset";
    }
    return collectionTypeLabel(mapOverType) ?? `nested ${mapOverType}`;
}

export type ProcessingSource = "datasets" | "collection";

/** The tool runs one job per selected item, or one job per part of the selected collection */
export interface BatchProcessingMode {
    kind: "batch";
    source: ProcessingSource;
    /** False when describing the field before anything is selected */
    hasSelection: boolean;
    /** One job per selected item (several datasets, or several collections) */
    perItem: boolean;
    /** Collection type handed to each job; unset when each job receives a single dataset */
    mapOverType?: CollectionType;
    /** Type of the selected collection, when known */
    collectionType?: CollectionType;
}

/** The input consumes the whole selection in a single job */
export interface BulkProcessingMode {
    kind: "bulk";
    source: ProcessingSource;
    /** False when describing the field before anything is selected */
    hasSelection: boolean;
    /** More than one item is selected */
    plural: boolean;
    /** Whether a nested collection could be mapped over this input to get one job per element */
    canNest: boolean;
}

export type ProcessingMode = BatchProcessingMode | BulkProcessingMode;

/** Whether a selection is submitted as a batch: a batch variant, or a collection flagged for map over */
export function isBatchSelection(variantBatch: string, values: DataOption[]): boolean {
    return variantBatch !== BATCH.DISABLED || values.some((v) => !!v.map_over_type);
}

/**
 * Whether wrapping the selection in one more `list` level makes the server map over this input
 * rather than match it directly. Untyped collection inputs accept anything directly.
 */
function canNestToMapOver(type: "data" | "data_collection", collectionTypes: CollectionType[]): boolean {
    if (type === "data") {
        return true;
    }
    // inputs accepting both X and list:X would match the nested collection directly
    const acceptsNested = collectionTypes.some((t) => collectionTypes.includes(`list:${t}`));
    return !acceptsNested && collectionTypes.some((t) => t.startsWith("list"));
}

/** Describe how a data input processes its selection, mirroring server job expansion */
export function getProcessingMode(
    variant: VariantInterface | null | undefined,
    type: "data" | "data_collection",
    values: DataOption[],
    collectionTypes: CollectionType[] = [],
): ProcessingMode | null {
    if (!variant) {
        return null;
    }
    const source: ProcessingSource = variant.src === SOURCE.DATASET ? "datasets" : "collection";
    const hasSelection = values.length > 0;
    if (isBatchSelection(variant.batch, values)) {
        const mode: BatchProcessingMode = { kind: "batch", source, hasSelection, perItem: values.length > 1 };
        const [single] = values;
        // the server only splits a collection when it is the sole batch value
        if (source === "collection" && values.length === 1 && single) {
            if (single.map_over_type && single.map_over_type !== SINGLE_DATASETS) {
                mode.mapOverType = single.map_over_type;
            }
            if (single.collection_type) {
                mode.collectionType = single.collection_type;
            }
        }
        return mode;
    }
    if (variant.multiple || type === "data_collection") {
        return {
            kind: "bulk",
            source,
            hasSelection,
            plural: values.length > 1,
            canNest: canNestToMapOver(type, collectionTypes),
        };
    }
    return null;
}
