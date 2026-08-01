export interface UniquelyKeyedItem {
    id: string;
    history_content_type: string;
}

/**
 * The key identifying a history content item within a listing, used for selection,
 * component refs and the DOM id `ContentItem` renders. Every listing of `ContentItem`
 * rows has to agree on it.
 */
export function itemUniqueKey(item: UniquelyKeyedItem): string {
    return `${item.history_content_type}-${item.id}`;
}
