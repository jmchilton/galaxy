/** The fields a history content item needs to be identified within a listing. */
export interface UniquelyKeyedItem {
    id: string;
    history_content_type: string;
}

/**
 * The key identifying a history content item within a listing.
 *
 * Used for selection, component refs and the DOM id `ContentItem` renders, so every
 * listing of `ContentItem` rows has to agree on it. Both the history panel and the
 * collection panel key rows this way.
 */
export function itemUniqueKey(item: UniquelyKeyedItem): string {
    return `${item.history_content_type}-${item.id}`;
}
