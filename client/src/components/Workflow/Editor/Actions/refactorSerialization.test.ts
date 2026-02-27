import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";

import { useConnectionStore } from "@/stores/workflowConnectionStore";
import { useWorkflowCommentStore } from "@/stores/workflowEditorCommentStore";
import { useWorkflowStateStore } from "@/stores/workflowEditorStateStore";
import { useWorkflowStepStore } from "@/stores/workflowStepStore";

import { fromSimple } from "../modules/model";
import {
    AddCommentAction,
    ChangeColorAction,
    DeleteCommentAction,
    LazyChangeDataAction,
    LazyChangePositionAction,
    LazyChangeSizeAction,
    RemoveAllFreehandCommentsAction,
} from "./commentActions";
import { ConnectStepAction, DisconnectStepAction } from "./connectionActions";
import { mockComment, mockFreehandComment, mockToolStep, mockWorkflow } from "./mockData";
import { buildBatchTitle, type SerializationResult, serializeAction } from "./refactorSerialization";
import {
    InsertStepAction,
    LazyMutateStepAction,
    LazySetLabelAction,
    LazySetOutputLabelAction,
    RemoveStepAction,
} from "./stepActions";
import { LazyMoveMultipleAction, LazySetValueAction } from "./workflowActions";

const workflowId = "mock-workflow";

function resetStores() {
    const stepStore = useWorkflowStepStore(workflowId);
    const stateStore = useWorkflowStateStore(workflowId);
    const connectionStore = useConnectionStore(workflowId);
    const commentStore = useWorkflowCommentStore(workflowId);
    stepStore.$reset();
    stateStore.$reset();
    connectionStore.$reset();
    commentStore.$reset();
    return { stepStore, stateStore, connectionStore, commentStore };
}

describe("refactorSerialization", () => {
    const pinia = createPinia();
    setActivePinia(pinia);

    let stores: ReturnType<typeof resetStores>;

    beforeEach(async () => {
        stores = resetStores();
        await fromSimple(workflowId, mockWorkflow());
        // Add a tool step (id=1) with outputs for tests that need it
        stores.stepStore.addStep(mockToolStep(1));
    });

    describe("Step Actions", () => {
        describe("serializeLabelChange", () => {
            it("serializes label change by order_index", () => {
                const step = stores.stepStore.getStep(0)!;
                const action = new LazySetLabelAction(
                    stores.stepStore,
                    stores.stateStore,
                    step.id,
                    step.label ?? null,
                    "New Label",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "update_step_label",
                    step: { order_index: 0 },
                    label: "New Label",
                });
            });

            it("serializes empty label", () => {
                const step = stores.stepStore.getStep(0)!;
                const action = new LazySetLabelAction(stores.stepStore, stores.stateStore, step.id, "Old Label", "");
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]!).toHaveProperty("label", "");
            });
        });

        describe("serializeOutputLabelChange", () => {
            it("serializes setting an output label", () => {
                const step = stores.stepStore.getStep(1)!;
                const toOutputs = [{ output_name: "out_file1", label: "MyOutput" }];
                const action = new LazySetOutputLabelAction(
                    stores.stepStore,
                    stores.stateStore,
                    step.id,
                    null,
                    "MyOutput",
                    toOutputs,
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "update_output_label",
                    output: { order_index: 1, output_name: "out_file1" },
                    output_label: "MyOutput",
                });
            });

            it("serializes clearing an output label", () => {
                const step = stores.stepStore.getStep(1)!;
                // Simulate step already having an output label via store update
                stores.stepStore.updateStep({
                    ...step,
                    workflow_outputs: [{ output_name: "out_file1", label: "OldLabel" }],
                });
                const action = new LazySetOutputLabelAction(
                    stores.stepStore,
                    stores.stateStore,
                    step.id,
                    "OldLabel",
                    "",
                    [], // empty = output removed
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_output_label",
                    output: { order_index: 1, output_name: "out_file1" },
                    output_label: "",
                });
            });
        });

        describe("serializePositionChange", () => {
            it("serializes step position change with absolute position", () => {
                const step = stores.stepStore.getStep(0)!;
                const action = new LazyMutateStepAction(stores.stepStore, step.id, "position", step.position, {
                    left: 500,
                    top: 600,
                });
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "update_step_position",
                    step: { order_index: 0 },
                    position_absolute: { left: 500, top: 600 },
                });
            });
        });

        describe("serializeAddStep", () => {
            it("serializes adding a tool step", () => {
                const action = new InsertStepAction(stores.stepStore, stores.stateStore, {
                    contentId: "cat1",
                    name: "Concatenate datasets",
                    type: "tool",
                    position: { left: 100, top: 200 },
                });
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "add_step",
                    type: "tool",
                    label: null,
                    position: { left: 100, top: 200 },
                    tool_state: null,
                });
            });

            it("serializes adding a data input", () => {
                const action = new InsertStepAction(stores.stepStore, stores.stateStore, {
                    contentId: null,
                    name: "Input dataset",
                    type: "data_input",
                    position: { left: 0, top: 0 },
                });
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]!).toHaveProperty("type", "data_input");
            });
        });

        describe("serializeRemoveStep", () => {
            it("serializes removing a step by order_index", () => {
                const step = stores.stepStore.getStep(1)!;
                const action = new RemoveStepAction(stores.stepStore, stores.stateStore, stores.connectionStore, step);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "remove_step",
                    step: { order_index: 1 },
                });
            });
        });
    });

    describe("Comment Actions", () => {
        describe("serializeAddComment", () => {
            it("serializes adding a text comment", () => {
                const comment = mockComment(0);
                const action = new AddCommentAction(stores.commentStore, comment);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "add_comment",
                    type: "text",
                    position: { left: 0, top: 0 },
                    size: { width: 170, height: 50 },
                    color: "none",
                    data: { size: 2, text: "Enter Text" },
                });
            });
        });

        describe("serializeDeleteComment", () => {
            it("serializes deleting a comment", () => {
                const comment = mockComment(5);
                stores.commentStore.addComments([comment]);
                const action = new DeleteCommentAction(stores.commentStore, comment);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "delete_comment",
                    comment: { comment_id: 5 },
                });
            });
        });

        describe("serializeChangeCommentColor", () => {
            it("serializes color change", () => {
                const comment = mockComment(3);
                stores.commentStore.addComments([comment]);
                const action = new ChangeColorAction(stores.commentStore, comment, "blue");
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_comment_color",
                    comment: { comment_id: 3 },
                    color: "blue",
                });
            });
        });

        describe("serializeChangeCommentData", () => {
            it("serializes data change", () => {
                const comment = mockComment(2);
                stores.commentStore.addComments([comment]);
                const newData = { size: 3, text: "Updated Text" };
                const action = new LazyChangeDataAction(stores.commentStore, comment, newData);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_comment_data",
                    comment: { comment_id: 2 },
                    data: { size: 3, text: "Updated Text" },
                });
            });
        });

        describe("serializeChangeCommentPosition", () => {
            it("serializes position change with tuple-to-dict conversion", () => {
                const comment = mockComment(1);
                stores.commentStore.addComments([comment]);
                const action = new LazyChangePositionAction(stores.commentStore, comment, [100, 200]);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_comment_position",
                    comment: { comment_id: 1 },
                    position: { left: 100, top: 200 },
                });
            });
        });

        describe("serializeChangeCommentSize", () => {
            it("serializes size change with tuple-to-dict conversion", () => {
                const comment = mockComment(4);
                stores.commentStore.addComments([comment]);
                const action = new LazyChangeSizeAction(stores.commentStore, comment, [300, 400]);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_comment_size",
                    comment: { comment_id: 4 },
                    size: { width: 300, height: 400 },
                });
            });
        });

        describe("serializeRemoveAllFreehand", () => {
            it("serializes remove all freehand comments", () => {
                stores.commentStore.addComments([mockFreehandComment(0), mockFreehandComment(1)]);
                const action = new RemoveAllFreehandCommentsAction(stores.commentStore);
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({ action_type: "remove_all_freehand_comments" });
            });
        });
    });

    describe("Workflow Metadata Actions", () => {
        describe("serializeWorkflowMetadata", () => {
            it("serializes name change", () => {
                const action = new LazySetValueAction(
                    "Old Name",
                    "New Name",
                    () => {},
                    () => {},
                    "name",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_name", name: "New Name" });
            });

            it("serializes annotation change", () => {
                const action = new LazySetValueAction(
                    "old",
                    "new annotation",
                    () => {},
                    () => {},
                    "annotation",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_annotation",
                    annotation: "new annotation",
                });
            });

            it("serializes license change", () => {
                const action = new LazySetValueAction(
                    "",
                    "MIT",
                    () => {},
                    () => {},
                    "license",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_license", license: "MIT" });
            });

            it("serializes creator change", () => {
                const creator = [{ name: "Test Author" }];
                const action = new LazySetValueAction(
                    [],
                    creator,
                    () => {},
                    () => {},
                    "creator",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_creator", creator });
            });

            it("returns error for unsupported metadata type", () => {
                const action = new LazySetValueAction(
                    "a",
                    "b",
                    () => {},
                    () => {},
                    "tags",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(false);
                expect(result.error).toContain("not yet supported");
            });
        });
    });

    describe("Move Multiple", () => {
        it("serializes moving steps and comments", () => {
            const comment = mockComment(0);
            stores.commentStore.addComments([comment]);

            const step = stores.stepStore.getStep(1)!;

            const action = new LazyMoveMultipleAction(
                stores.commentStore,
                stores.stepStore,
                [comment],
                [step as typeof step & { position: { left: number; top: number } }],
                { x: 0, y: 0 },
                { x: 50, y: 100 },
            );

            const result = serializeAction(action);
            expect(result.success).toBe(true);

            const stepActions = result.actions.filter((a) => a.action_type === "update_step_position");
            const commentActions = result.actions.filter((a) => a.action_type === "update_comment_position");
            expect(stepActions).toHaveLength(1);
            expect(commentActions).toHaveLength(1);

            // Step: original position {left:300,top:100}, offset from origin = [300,100]
            // Final = positionTo(50,100) + offset(300,100) = {left:350, top:200}
            expect(stepActions[0]).toHaveProperty("position_absolute", { left: 350, top: 200 });

            // Comment: original position [0,0], offset from origin = [0,0]
            // Final = positionTo(50,100) + offset(0,0) = {left:50, top:100}
            expect(commentActions[0]).toHaveProperty("position", { left: 50, top: 100 });
        });
    });

    describe("Connection Actions", () => {
        it("serializes connecting two steps", () => {
            const connection = {
                input: { stepId: 1, name: "input1", connectorType: "input" as const },
                output: { stepId: 0, name: "output", connectorType: "output" as const },
            };
            const action = new ConnectStepAction(
                connection,
                () => {},
                () => {},
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toEqual({
                action_type: "connect",
                input: { order_index: 1, input_name: "input1" },
                output: { order_index: 0, output_name: "output" },
            });
        });

        it("serializes connection from input step (output_name convention = 'output')", () => {
            // Input/data steps in Galaxy have a single output named "output" by convention.
            // The backend OutputReferenceByOrderIndex.output_name defaults to "output" when None,
            // but we always send it explicitly to avoid relying on the backend default.
            const connection = {
                input: { stepId: 2, name: "input1", connectorType: "input" as const },
                output: { stepId: 0, name: "output", connectorType: "output" as const },
            };
            const action = new ConnectStepAction(
                connection,
                () => {},
                () => {},
            );
            const result = serializeAction(action);
            expect(result.actions[0]).toHaveProperty("output");
            const output = (result.actions[0] as any).output;
            expect(output.output_name).toBe("output");
        });

        it("serializes disconnecting two steps", () => {
            const connection = {
                input: { stepId: 1, name: "input1", connectorType: "input" as const },
                output: { stepId: 0, name: "output", connectorType: "output" as const },
            };
            const action = new DisconnectStepAction(
                connection,
                () => {},
                () => {},
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toEqual({
                action_type: "disconnect",
                input: { order_index: 1, input_name: "input1" },
                output: { order_index: 0, output_name: "output" },
            });
        });
    });

    describe("Workflow Report", () => {
        it("serializes readme/report change", () => {
            const action = new LazySetValueAction(
                "",
                "# Report",
                () => {},
                () => {},
                "readme",
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toEqual({
                action_type: "update_report",
                report: { markdown: "# Report" },
            });
        });
    });

    describe("Dispatcher", () => {
        it("returns error for unsupported action types", () => {
            const action = { name: "unknown", run() {}, undo() {}, redo() {} };
            const result = serializeAction(action as any);
            expect(result.success).toBe(false);
            expect(result.error).toContain("not yet supported");
        });

        it("catches serialization errors gracefully", () => {
            const action = Object.create(LazySetLabelAction.prototype);
            action.stepId = undefined;
            action.toValue = undefined;
            const result = serializeAction(action);
            expect(result).toHaveProperty("success");
        });
    });
});

function makeSerialization(title: string): SerializationResult {
    return { actions: [], title, success: true };
}

describe("buildBatchTitle", () => {
    it("returns single title unchanged", () => {
        expect(buildBatchTitle([makeSerialization("Move step")])).toBe("Move step");
    });

    it("joins multiple titles with semicolons", () => {
        const result = buildBatchTitle([makeSerialization("Move step"), makeSerialization("Add step")]);
        expect(result).toBe("Move step; Add step");
    });

    it("collapses adjacent duplicate titles", () => {
        const result = buildBatchTitle([
            makeSerialization("Move step"),
            makeSerialization("Move step"),
            makeSerialization("Add step"),
            makeSerialization("Add step"),
            makeSerialization("Move step"),
        ]);
        expect(result).toBe("Move step; Add step; Move step");
    });

    it("truncates at 200 characters", () => {
        const result = buildBatchTitle([
            makeSerialization("A".repeat(100)),
            makeSerialization("B".repeat(100)),
            makeSerialization("C".repeat(100)),
        ]);
        expect(result.length).toBeLessThanOrEqual(200);
        expect(result).toMatch(/\.\.\.$/);
    });

    it("returns empty string for empty input", () => {
        expect(buildBatchTitle([])).toBe("");
    });
});
