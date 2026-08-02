import type { Ref } from "vue";

import type Filtering from "@/utils/filtering";

/** Configures "Query Selection Mode": selecting everything a filter matches, including
 * items that are not loaded.
 *
 * Only a listing backed by a filterable query can offer this. Omit it and the composable
 * selects only what is in `allItems` and reports the true count, which is what a listing
 * with no query behind it — a collection's elements, say — should do.
 */
export interface QuerySelectionOptions {
    /** The current filter text. */
    filterText: Ref<string>;
    /** The count of items in the current query. */
    totalItemsInQuery: Ref<number>;
    /** The filtering class used to check query selection. */
    filterClass: Filtering<any>;
    /** A method called when the "Query Selection Mode" is broken. */
    querySelectionBreak?: () => void;
}

export interface SelectedItemsProps<T> {
    /** A unique key to watch and reset selection when it changes. */
    scopeKey: Ref<string>;
    /** A method that returns a unique key for each item. */
    getItemKey: (item: T) => string;
    /** A list of all items. */
    allItems: Ref<T[]>;
    /** If the items are selectable. */
    selectable: Ref<boolean>;
    /** Enables selecting beyond the loaded items. Omit for a listing with no query. */
    querySelection?: QuerySelectionOptions;
    /** A method called when an item is deleted. */
    onDelete: (item: T, recursive: boolean) => void;
    /** The class name for the element that is used for keydown selection/navigation. */
    expectedKeyDownClass?: string;
    /** A list of class names that are not allowed to be used for keydown selection/navigation. */
    disallowedKeyDownClasses?: string[];
    /** The element attribute used for range selection.
     * @default "id"
     * @example Could instead be `data-id` in
     *          ```html
     *          <div data-id="1">
     *          ```
     */
    attributeForRangeSelection?: string;
    /** A method that returns the value for the attribute used for range selection.
     * If not provided, the `getItemKey` method will be used.
     */
    getAttributeForRangeSelection?: (item: T) => string;
}

export type ComponentInstanceRef<T extends ComponentInstanceExtends> = Record<string, Ref<InstanceType<T> | null>>;
export type ComponentInstanceExtends = abstract new (...args: any) => any;
