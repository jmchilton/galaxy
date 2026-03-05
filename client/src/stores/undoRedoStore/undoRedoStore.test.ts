import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SerializationResult } from "@/components/Workflow/Editor/Actions/refactorSerialization";
import { useConfigStore } from "@/stores/configurationStore";

import { UndoRedoAction } from "./undoRedoAction";

const mockSerializeAction = vi.fn<(action: UndoRedoAction) => SerializationResult>();

vi.mock("@/components/Workflow/Editor/Actions/refactorSerialization", () => ({
    serializeAction: (...args: unknown[]) => mockSerializeAction(args[0] as UndoRedoAction),
    // re-export the type — not needed at runtime but keeps TS happy
    buildBatchTitle: vi.fn(),
}));

// Must import after vi.mock
const { useUndoRedoStore } = await import("./index");

const workflowId = "test-workflow";

class TestAction extends UndoRedoAction {
    ran = false;
    undone = false;

    run() {
        this.ran = true;
    }

    undo() {
        this.undone = true;
    }
}

function makeSuccessResult(title = "test action"): SerializationResult {
    return {
        actions: [{ action_type: "update_name" as const, name: "test" }],
        title,
        success: true,
    };
}

function makeFailResult(): SerializationResult {
    return { actions: [], title: "failed", success: false, error: "unsupported" };
}

describe("undoRedoStore persistence", () => {
    beforeEach(() => {
        setActivePinia(createPinia());
        mockSerializeAction.mockReset();
    });

    function enablePersistence() {
        const configStore = useConfigStore();
        configStore.config = { enable_workflow_action_persistence: true };
    }

    function disablePersistence() {
        const configStore = useConfigStore();
        configStore.config = { enable_workflow_action_persistence: false };
    }

    describe("applyAction with persistence enabled", () => {
        it("serializes and queues pending action", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action = new TestAction();
            store.applyAction(action);

            expect(mockSerializeAction).toHaveBeenCalledWith(action);
            expect(store.pendingActions.length).toBe(1);
            expect(store.pendingActions[0]!.actionId).toBe(action.id);
            expect(store.hasPendingActions).toBe(true);
        });

        it("does not queue failed serializations", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeFailResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());

            expect(store.pendingActions.length).toBe(0);
            expect(store.hasPendingActions).toBe(false);
        });
    });

    describe("applyAction with persistence disabled", () => {
        it("does not serialize or queue", () => {
            disablePersistence();

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());

            expect(mockSerializeAction).not.toHaveBeenCalled();
            expect(store.pendingActions.length).toBe(0);
        });
    });

    describe("undo", () => {
        it("removes matching pending action", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action = new TestAction();
            store.applyAction(action);

            expect(store.pendingActions.length).toBe(1);

            store.undo();

            expect(store.pendingActions.length).toBe(0);
        });

        it("only removes the undone action, not others", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action1 = new TestAction();
            const action2 = new TestAction();
            store.applyAction(action1);
            store.applyAction(action2);

            expect(store.pendingActions.length).toBe(2);

            store.undo(); // undoes action2

            expect(store.pendingActions.length).toBe(1);
            expect(store.pendingActions[0]!.actionId).toBe(action1.id);
        });
    });

    describe("redo", () => {
        it("re-serializes and re-adds to pending", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action = new TestAction();
            store.applyAction(action);
            store.undo();

            expect(store.pendingActions.length).toBe(0);

            store.redo();

            expect(store.pendingActions.length).toBe(1);
            expect(store.pendingActions[0]!.actionId).toBe(action.id);
            // serializeAction called twice: once for apply, once for redo
            expect(mockSerializeAction).toHaveBeenCalledTimes(2);
        });
    });

    describe("flushPendingActions", () => {
        it("returns and clears pending actions with allSerialized true", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());
            store.applyAction(new TestAction());

            expect(store.pendingActions.length).toBe(2);

            const { pending, allSerialized } = store.flushPendingActions();

            expect(pending.length).toBe(2);
            expect(allSerialized).toBe(true);
            expect(store.pendingActions.length).toBe(0);
            expect(store.hasPendingActions).toBe(false);
        });

        it("returns allSerialized false when any action failed", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValueOnce(makeSuccessResult()).mockReturnValueOnce(makeFailResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());
            store.applyAction(new TestAction());

            const { pending, allSerialized } = store.flushPendingActions();

            expect(pending.length).toBe(1); // only the successful one
            expect(allSerialized).toBe(false);
        });

        it("resets allActionsSerialized after flush", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeFailResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());

            expect(store.allActionsSerialized).toBe(false);

            store.flushPendingActions();

            expect(store.allActionsSerialized).toBe(true);
        });
    });

    describe("restorePendingActions", () => {
        it("prepends restored actions before any new ones accumulated during save", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);

            // Simulate two actions that were flushed for save
            const action1 = new TestAction();
            const action2 = new TestAction();
            store.applyAction(action1);
            store.applyAction(action2);
            const { pending } = store.flushPendingActions();

            // User performs a new action during the async save
            const action3 = new TestAction();
            store.applyAction(action3);
            expect(store.pendingActions.length).toBe(1);

            // Save fails — restore the flushed batch
            store.restorePendingActions(pending, true);

            expect(store.pendingActions.length).toBe(3);
            // Restored batch comes first, then the new action
            expect(store.pendingActions[0]!.actionId).toBe(action1.id);
            expect(store.pendingActions[1]!.actionId).toBe(action2.id);
            expect(store.pendingActions[2]!.actionId).toBe(action3.id);
        });

        it("restores allActionsSerialized to false when original batch was not fully serialized", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());
            store.flushPendingActions();

            // After flush, allActionsSerialized is reset to true
            expect(store.allActionsSerialized).toBe(true);

            // Restore with wasSerialized=false
            store.restorePendingActions([], false);

            expect(store.allActionsSerialized).toBe(false);
        });
    });

    describe("allActionsSerialized", () => {
        it("is true when all actions serialize successfully", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());
            store.applyAction(new TestAction());

            expect(store.allActionsSerialized).toBe(true);
        });

        it("is false when any action fails serialization", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValueOnce(makeSuccessResult()).mockReturnValueOnce(makeFailResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());
            store.applyAction(new TestAction());

            expect(store.allActionsSerialized).toBe(false);
        });
    });

    describe("$reset", () => {
        it("clears pending actions", () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            store.applyAction(new TestAction());

            expect(store.pendingActions.length).toBe(1);

            store.$reset();

            expect(store.pendingActions.length).toBe(0);
            expect(store.hasPendingActions).toBe(false);
        });
    });

    describe("async action serialization", () => {
        class AsyncTestAction extends UndoRedoAction {
            resolve!: () => void;
            reject!: (err: Error) => void;
            private promise: Promise<void>;

            constructor() {
                super();
                this.promise = new Promise<void>((resolve, reject) => {
                    this.resolve = resolve;
                    this.reject = reject;
                });
            }

            run() {
                return this.promise;
            }
        }

        it("defers serialization until async run resolves", async () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action = new AsyncTestAction();
            store.applyAction(action);

            // Before resolve: action is on undo stack but not yet serialized
            expect(store.undoActionStack.length).toBe(1);
            expect(store.asyncSerializationsInFlight).toBe(1);
            expect(mockSerializeAction).not.toHaveBeenCalled();

            action.resolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));

            expect(mockSerializeAction).toHaveBeenCalledWith(action);
            expect(store.pendingActions.length).toBe(1);
        });

        it("does not serialize if action was undone before async resolves", async () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action = new AsyncTestAction();
            store.applyAction(action);

            // Undo before the async completes
            store.undo();

            action.resolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));

            // Should NOT have serialized — action was removed from undo stack
            expect(mockSerializeAction).not.toHaveBeenCalled();
            expect(store.pendingActions.length).toBe(0);
        });

        it("sets allActionsSerialized false on async rejection", async () => {
            enablePersistence();

            const store = useUndoRedoStore(workflowId);
            const action = new AsyncTestAction();
            store.applyAction(action);

            action.reject(new Error("ELK failed"));
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));

            expect(store.allActionsSerialized).toBe(false);
            expect(mockSerializeAction).not.toHaveBeenCalled();
        });

        it("defers serialization on redo of async action", async () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            // Action that creates a fresh promise per run() call
            let currentResolve!: () => void;
            const action = new (class extends UndoRedoAction {
                run() {
                    return new Promise<void>((resolve) => {
                        currentResolve = resolve;
                    });
                }
            })();

            const store = useUndoRedoStore(workflowId);
            store.applyAction(action);

            // Resolve initial apply
            currentResolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));
            expect(store.pendingActions.length).toBe(1);
            mockSerializeAction.mockClear();

            // Undo removes pending action
            store.undo();
            expect(store.pendingActions.length).toBe(0);

            // Redo calls run() again → new promise → should defer serialization
            store.redo();

            expect(store.asyncSerializationsInFlight).toBe(1);
            expect(mockSerializeAction).not.toHaveBeenCalled();

            currentResolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));

            expect(mockSerializeAction).toHaveBeenCalledWith(action);
            expect(store.pendingActions.length).toBe(1);
        });

        it("tracks multiple concurrent async actions", async () => {
            enablePersistence();
            mockSerializeAction.mockReturnValue(makeSuccessResult());

            const store = useUndoRedoStore(workflowId);
            const action1 = new AsyncTestAction();
            const action2 = new AsyncTestAction();
            store.applyAction(action1);
            store.applyAction(action2);

            expect(store.asyncSerializationsInFlight).toBe(2);

            action1.resolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(1));

            action2.resolve();
            await vi.waitFor(() => expect(store.asyncSerializationsInFlight).toBe(0));

            expect(store.pendingActions.length).toBe(2);
        });
    });
});
