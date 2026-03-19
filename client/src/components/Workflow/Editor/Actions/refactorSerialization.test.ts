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
    AutoLayoutAction,
    CopyStepAction,
    InsertStepAction,
    LazyMutateStepAction,
    LazySetLabelAction,
    LazySetOutputLabelAction,
    RemoveStepAction,
    SetDataAction,
    UpdateStepAction,
} from "./stepActions";
import { CopyIntoWorkflowAction, LazyMoveMultipleAction, LazySetValueAction } from "./workflowActions";

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

        describe("serializeStepAnnotation", () => {
            it("serializes step annotation change", () => {
                const step = stores.stepStore.getStep(0)!;
                const action = new LazyMutateStepAction(stores.stepStore, step.id, "annotation", "", "My annotation");
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions).toHaveLength(1);
                expect(result.actions[0]).toEqual({
                    action_type: "update_step_annotation",
                    step: { order_index: 0 },
                    annotation: "My annotation",
                });
            });
        });

        describe("serializeAddStep", () => {
            it("serializes adding a tool step with content_id", () => {
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
                    content_id: "cat1",
                });
            });

            it("serializes adding a data input with null content_id", () => {
                const action = new InsertStepAction(stores.stepStore, stores.stateStore, {
                    contentId: null,
                    name: "Input dataset",
                    type: "data_input",
                    position: { left: 0, top: 0 },
                });
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]!).toHaveProperty("type", "data_input");
                expect(result.actions[0]!).toHaveProperty("content_id", null);
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

    describe("serializeCopyStep", () => {
        it("serializes CopyStepAction with full step data", () => {
            const step = stores.stepStore.getStep(1)!;
            const action = new CopyStepAction(stores.stepStore, stores.stateStore, step);
            // CopyStepAction clones the step, so action.step has all fields
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            const a = result.actions[0] as Record<string, unknown>;
            expect(a).toHaveProperty("action_type", "add_step");
            expect(a).toHaveProperty("type", "tool");
            expect(a).toHaveProperty("content_id", "cat1");
        });

        it("includes input_connections when present", () => {
            const step = stores.stepStore.getStep(1)!;
            const action = new CopyStepAction(stores.stepStore, stores.stateStore, step);
            const result = serializeAction(action);
            const a = result.actions[0] as Record<string, unknown>;
            expect(a).toHaveProperty("input_connections");
        });
    });

    describe("serializeUpdateStep", () => {
        it("serializes UpdateStepAction with tool_state change", () => {
            const step = stores.stepStore.getStep(1)!;
            const action = new UpdateStepAction(
                stores.stepStore,
                stores.stateStore,
                step.id,
                { tool_state: step.tool_state },
                { tool_state: { new_param: "new_value" } },
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toMatchObject({
                action_type: "update_step",
                step: { order_index: 1 },
                tool_state: { new_param: "new_value" },
            });
        });

        it("serializes UpdateStepAction with post_job_actions change", () => {
            const step = stores.stepStore.getStep(1)!;
            const newPjas = {
                HideDatasetActionout_file1: {
                    action_type: "HideDatasetAction",
                    output_name: "out_file1",
                    action_arguments: {},
                },
            };
            const action = new UpdateStepAction(
                stores.stepStore,
                stores.stateStore,
                step.id,
                { post_job_actions: step.post_job_actions },
                { post_job_actions: newPjas },
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions[0]).toMatchObject({
                action_type: "update_step",
                post_job_actions: newPjas,
            });
        });

        it("serializes UpdateStepAction with workflow_outputs change", () => {
            const step = stores.stepStore.getStep(1)!;
            const newOutputs = [{ output_name: "out_file1", label: "MyOutput" }];
            const action = new UpdateStepAction(
                stores.stepStore,
                stores.stateStore,
                step.id,
                { workflow_outputs: step.workflow_outputs },
                { workflow_outputs: newOutputs },
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions[0]).toMatchObject({
                action_type: "update_step",
                workflow_outputs: newOutputs,
            });
        });

        it("serializes mixed diff with multiple refactorable fields", () => {
            const step = stores.stepStore.getStep(1)!;
            const action = new UpdateStepAction(
                stores.stepStore,
                stores.stateStore,
                step.id,
                { tool_state: step.tool_state, post_job_actions: step.post_job_actions },
                {
                    tool_state: { mixed: true },
                    post_job_actions: { pja: { action_type: "x", output_name: "o", action_arguments: {} } },
                },
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            const a = result.actions[0] as Record<string, unknown>;
            expect(a).toHaveProperty("tool_state", { mixed: true });
            expect(a).toHaveProperty("post_job_actions", {
                pja: { action_type: "x", output_name: "o", action_arguments: {} },
            });
        });

        it("returns success with empty actions for derived-only diff", () => {
            const step = stores.stepStore.getStep(1)!;
            // Only `inputs` changed — a derived field
            const action = new UpdateStepAction(
                stores.stepStore,
                stores.stateStore,
                step.id,
                { inputs: step.inputs },
                {
                    inputs: [
                        {
                            name: "new_input",
                            label: "x",
                            multiple: false,
                            extensions: ["data"],
                            optional: false,
                            input_type: "dataset",
                        },
                    ],
                },
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(0);
        });

        it("serializes SetDataAction (extends UpdateStepAction)", () => {
            const step = stores.stepStore.getStep(1)!;
            const modified = { ...step, tool_state: { changed_param: "yes" } };
            const action = new SetDataAction(stores.stepStore, stores.stateStore, step, modified);
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toMatchObject({
                action_type: "update_step",
                step: { order_index: 1 },
                tool_state: { changed_param: "yes" },
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

            it("serializes tags change", () => {
                const action = new LazySetValueAction(
                    ["old"],
                    ["new1", "new2"],
                    () => {},
                    () => {},
                    "tags",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_tags", tags: ["new1", "new2"] });
            });

            it("serializes help change", () => {
                const action = new LazySetValueAction(
                    "",
                    "Help text",
                    () => {},
                    () => {},
                    "help",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_help", help: "Help text" });
            });

            it("serializes logoUrl change", () => {
                const action = new LazySetValueAction(
                    null,
                    "https://example.com/logo.png",
                    () => {},
                    () => {},
                    "logoUrl",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({
                    action_type: "update_logo_url",
                    logo_url: "https://example.com/logo.png",
                });
            });

            it("serializes doi change", () => {
                const action = new LazySetValueAction(
                    [],
                    ["10.1234/test"],
                    () => {},
                    () => {},
                    "doi",
                );
                const result = serializeAction(action);
                expect(result.success).toBe(true);
                expect(result.actions[0]).toEqual({ action_type: "update_doi", doi: ["10.1234/test"] });
            });

            it("returns error for unsupported metadata type", () => {
                const action = new LazySetValueAction(
                    "a",
                    "b",
                    () => {},
                    () => {},
                    "unknownField",
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

    describe("Workflow Report and Readme", () => {
        it("serializes report change (what='report')", () => {
            const action = new LazySetValueAction(
                "",
                "# Report",
                () => {},
                () => {},
                "report",
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toEqual({
                action_type: "update_report",
                report: { markdown: "# Report" },
            });
        });

        it("serializes readme change (what='readme')", () => {
            const action = new LazySetValueAction(
                "",
                "This is the readme",
                () => {},
                () => {},
                "readme",
            );
            const result = serializeAction(action);
            expect(result.success).toBe(true);
            expect(result.actions).toHaveLength(1);
            expect(result.actions[0]).toEqual({
                action_type: "update_readme",
                readme: "This is the readme",
            });
        });

        it("readme and report produce different action_types", () => {
            const readmeAction = new LazySetValueAction(
                "",
                "readme text",
                () => {},
                () => {},
                "readme",
            );
            const reportAction = new LazySetValueAction(
                "",
                "report text",
                () => {},
                () => {},
                "report",
            );
            const readmeResult = serializeAction(readmeAction);
            const reportResult = serializeAction(reportAction);
            expect((readmeResult.actions[0] as any).action_type).toBe("update_readme");
            expect((reportResult.actions[0] as any).action_type).toBe("update_report");
        });
    });

    describe("CopyIntoWorkflowAction", () => {
        it("serializes paste with steps and a comment, remaps input_connections", () => {
            const pasteData = {
                name: "Pasted Workflow",
                steps: {
                    "0": {
                        ...mockToolStep(0),
                        type: "data_input" as const,
                        content_id: null,
                        input_connections: {},
                        tool_state: {},
                    },
                    "1": {
                        ...mockToolStep(1),
                        input_connections: { input1: [{ output_name: "output", id: 0 }] },
                    },
                },
                comments: [mockComment(0)],
            };

            const action = new CopyIntoWorkflowAction(workflowId, pasteData as any, { left: 50, top: 50 });
            action.run();

            const result = serializeAction(action);
            expect(result.success).toBe(true);

            // 2 add_step + 1 add_comment = 3 actions
            const addSteps = result.actions.filter((a) => a.action_type === "add_step");
            const addComments = result.actions.filter((a) => a.action_type === "add_comment");
            expect(addSteps).toHaveLength(2);
            expect(addComments).toHaveLength(1);

            // The second step's input_connections should reference the new ID of the first step
            const secondStep = addSteps[1] as Record<string, any>;
            const conns = secondStep.input_connections;
            expect(conns).toBeDefined();
            // The remapped ID should be one of the newStepIds (not the original 0)
            const connLink = conns.input1[0];
            expect(action.newStepIds).toContain(connLink.id);
        });

        it("returns failure when no steps/comments pasted", () => {
            const pasteData = { name: "Empty", steps: {}, comments: [] };
            const action = new CopyIntoWorkflowAction(workflowId, pasteData as any, { left: 0, top: 0 });
            // Don't run — newStepIds stays empty
            const result = serializeAction(action);
            expect(result.success).toBe(false);
        });
    });

    describe("AutoLayoutAction", () => {
        it("serializes auto layout with step and comment positions", () => {
            const action = new AutoLayoutAction(workflowId);
            // Manually set positions as if run() completed
            action.positions = {
                steps: [
                    { id: "0", x: 100, y: 200 },
                    { id: "1", x: 300, y: 400 },
                ],
                comments: [{ id: "0", x: 50, y: 60, w: 170, h: 50 }],
            };

            const result = serializeAction(action);
            expect(result.success).toBe(true);

            const stepPositions = result.actions.filter((a) => a.action_type === "update_step_position");
            const commentPositions = result.actions.filter((a) => a.action_type === "update_comment_position");
            const commentSizes = result.actions.filter((a) => a.action_type === "update_comment_size");

            expect(stepPositions).toHaveLength(2);
            expect(commentPositions).toHaveLength(1);
            expect(commentSizes).toHaveLength(1);

            expect(stepPositions[0]).toEqual({
                action_type: "update_step_position",
                step: { order_index: 0 },
                position_absolute: { left: 100, top: 200 },
            });
            expect(commentPositions[0]).toEqual({
                action_type: "update_comment_position",
                comment: { comment_id: 0 },
                position: { left: 50, top: 60 },
            });
            expect(commentSizes[0]).toEqual({
                action_type: "update_comment_size",
                comment: { comment_id: 0 },
                size: { width: 170, height: 50 },
            });
        });

        it("returns failure when positions are empty", () => {
            const action = new AutoLayoutAction(workflowId);
            // positions default to empty arrays
            const result = serializeAction(action);
            expect(result.success).toBe(false);
            expect(result.error).toContain("not available");
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
