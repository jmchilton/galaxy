import type { CollectionType } from "@/api/datasetCollections";
import { collectionTypeLabel } from "@/components/Collections/common/buildCollectionModal";
import localize from "@/utils/localization";

import { mapOverUnit, matchCollectionType, SINGLE_DATASETS } from "./collectionMatch";
import type { DataOption } from "./types";
import { isBatchSelection, SOURCE, type VariantInterface } from "./variants";

/** Help terms explaining how a data input is processed */
export const PROCESSING_HELP_TERMS = {
    mapOver: "galaxy.collections.mapOver",
    reduction: "galaxy.collections.reduction",
    nestToMapOver: "galaxy.collections.nestToMapOver",
} as const;

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

/**
 * Whether wrapping the selected list in one more `list` level makes the server map over this input
 * rather than match it directly. Before a selection, every accepted type must agree, since a nested
 * collection the input matches directly would still run as one job. Untyped collection inputs accept
 * anything directly.
 */
function canNestToMapOver(
    type: "data" | "data_collection",
    collectionTypes: CollectionType[],
    values: DataOption[],
): boolean {
    if (type === "data") {
        return true;
    }
    const nested = (t: CollectionType) => matchCollectionType(`list:${t}`, collectionTypes);
    const nestsToMapOver = (t: CollectionType) => t.startsWith("list") && !!nested(t)?.mapOverType;
    const selected = values.length === 1 ? values[0]?.collection_type : undefined;
    if (selected && matchCollectionType(selected, collectionTypes)?.mapOverType === null) {
        return nestsToMapOver(selected);
    }
    return collectionTypes.some(nestsToMapOver) && !collectionTypes.some((t) => nested(t)?.mapOverType === null);
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
            canNest: canNestToMapOver(type, collectionTypes, values),
        };
    }
    return null;
}

/** A help link within a processing hint */
export interface HintLink {
    text: string;
    uri: string;
}

/**
 * A processing hint sentence: `lead`, then a raw collection type and the words after it (for types
 * without a label), a help `link`, and `tail` right after the link; `nest` suggests nesting to map over.
 */
export interface ProcessingHintText {
    lead: string;
    code?: { type: string; after: string };
    link: HintLink;
    tail: string;
    nest?: HintLink;
}

function bulkLead(mode: BulkProcessingMode): string {
    if (mode.source === "datasets") {
        return localize(mode.hasSelection ? "All selected datasets will be" : "Datasets selected here will be");
    }
    if (mode.plural) {
        return localize("The selected collections will be");
    }
    return localize(mode.hasSelection ? "The selected collection will be" : "A collection selected here will be");
}

/** The hint sentence explaining a processing mode */
export function describeProcessingMode(mode: ProcessingMode): ProcessingHintText {
    if (mode.kind === "bulk") {
        const whole = mode.source === "collection" && !mode.plural;
        return {
            lead: bulkLead(mode),
            link: {
                text: localize(whole ? "processed as a whole in a single job" : "processed together in a single job"),
                uri: PROCESSING_HELP_TERMS.reduction,
            },
            tail: ".",
            nest: mode.canNest
                ? {
                      text: localize(
                          mode.source === "datasets" ? "Need one job per dataset?" : "Need one job per element?",
                      ),
                      uri: PROCESSING_HELP_TERMS.nestToMapOver,
                  }
                : undefined,
        };
    }
    if (mode.source === "datasets" || mode.perItem) {
        let lead = "Each selected collection will be";
        if (mode.source === "datasets") {
            lead = mode.hasSelection ? "Each selected dataset will be" : "Each dataset selected here will be";
        }
        return {
            lead: localize(lead),
            link: { text: localize("run as a separate job"), uri: PROCESSING_HELP_TERMS.mapOver },
            tail: `, ${localize("matched in order with other batch inputs.")}`,
        };
    }
    // a single collection split into one job per part
    const mapOver = {
        link: { text: localize("mapped over"), uri: PROCESSING_HELP_TERMS.mapOver },
        tail: ` ${localize("this tool: one job per")} ${localize(mapOverUnit(mode.mapOverType))}.`,
    };
    const willBe = localize("will be");
    if (!mode.hasSelection) {
        return { lead: `${localize("A collection selected here")} ${willBe}`, ...mapOver };
    }
    const label = mode.collectionType && collectionTypeLabel(mode.collectionType);
    if (label) {
        return { lead: `${localize("The selected")} ${label} ${willBe}`, ...mapOver };
    }
    const after = `${localize("collection")} ${willBe}`;
    if (mode.collectionType) {
        return { lead: localize("The selected"), code: { type: mode.collectionType, after }, ...mapOver };
    }
    return { lead: `${localize("The selected")} ${after}`, ...mapOver };
}
