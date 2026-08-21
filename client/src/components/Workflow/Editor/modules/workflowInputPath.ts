/**
 * Translate between persisted workflow connection names and `when` input paths.
 *
 * Galaxy flattens nested tool inputs with `|` in `input_connections`, while expression
 * code addresses the same input one property at a time. Keep comparisons segmented:
 * joining an expression path is lossy when a literal property name itself contains `|`.
 */

/** Map a flat, pipe-delimited connection name onto its nested `inputs` path. */
export function connectionNameToInputPath(inputName: string): string[] {
    return inputName.split("|");
}

/** True when `targetPath` names `referencedPath` or one of its ancestors. */
export function inputPathIsPrefix(targetPath: readonly string[], referencedPath: readonly string[]): boolean {
    if (targetPath.length > referencedPath.length) {
        return false;
    }
    return targetPath.every((segment, position) => segment === referencedPath[position]);
}
