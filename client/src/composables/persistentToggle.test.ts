import { runInTestScope } from "@tests/vitest/effectScope";
import { createPinia, disposePinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, onTestFinished } from "vitest";

import { usePersistentToggle } from "./persistentToggle";

describe("usePersistentToggle", () => {
    beforeEach(() => {
        const storedSalt = localStorage.getItem("local-storage-salt");
        localStorage.removeItem("local-storage-salt");
        onTestFinished(() => {
            if (storedSalt === null) {
                localStorage.removeItem("local-storage-salt");
            } else {
                localStorage.setItem("local-storage-salt", storedSalt);
            }
        });
        const pinia = createPinia();
        setActivePinia(pinia);
        onTestFinished(() => disposePinia(pinia));
    });

    it("starts off by default", () => {
        expect(runInTestScope(() => usePersistentToggle("test-default")).toggled.value).toBe(false);
    });

    it("starts at the given initial value and toggles from there", () => {
        const { toggled, toggle } = runInTestScope(() => usePersistentToggle("test-initially-on", true));
        expect(toggled.value).toBe(true);
        toggle();
        expect(toggled.value).toBe(false);
    });
});
