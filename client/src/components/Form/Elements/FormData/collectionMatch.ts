import type { CollectionType } from "@/api/datasetCollections";
import { CollectionTypeDescription } from "@/components/Workflow/Editor/modules/collectionTypeDescription";

/** Map-over type the server assigns when a `paired_or_unpaired` input is fed a plain list */
export const SINGLE_DATASETS = "single_datasets";

/**
 * How a collection feeds an input accepting `inputTypes`, mirroring the server's option listing: directly
 * (`mapOverType: null`), mapped over the deepest input type it nests, or not at all (`null`).
 */
export function matchCollectionType(
    collectionType: CollectionType,
    inputTypes: CollectionType[],
): { mapOverType: CollectionType | null } | null {
    const item = new CollectionTypeDescription(collectionType);
    const inputs = inputTypes.map((inputType) => new CollectionTypeDescription(inputType));
    if (inputs.some((input) => input.accepts(item))) {
        return { mapOverType: null };
    }
    // deepest first, so each job gets as much data as possible
    const mapOver = [...inputs].sort((a, b) => b.rank - a.rank).find((input) => item.canMapOver(input));
    if (!mapOver) {
        return null;
    }
    if (mapOver.collectionType === "paired_or_unpaired" && !collectionType.endsWith("paired_or_unpaired")) {
        return { mapOverType: collectionType.endsWith("paired") ? "paired" : SINGLE_DATASETS };
    }
    return { mapOverType: mapOver.collectionType };
}
