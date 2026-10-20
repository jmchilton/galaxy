/** A promise that settles when the returned `release` is called, e.g. to hold a mocked response open. */
export function hold() {
    let release: () => void = () => {};
    const released = new Promise<void>((resolve) => {
        release = resolve;
    });
    return { released, release };
}
