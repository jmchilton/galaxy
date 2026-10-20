/**
 * Tracks overlapping requests so only the most recently started one applies its result.
 *
 * @returns A function that marks the start of a request and returns whether that request is still the latest.
 */
export function createLatestRequestTracker() {
    let latest = 0;
    return function startRequest() {
        const request = ++latest;
        return () => request === latest;
    };
}
