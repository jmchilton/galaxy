/**
 * Serializes frontend undo/redo actions into backend refactor API actions.
 *
 * Pure serialization layer — no API calls. Converts TypeScript action class instances
 * into JSON payloads matching the backend RefactorRequest schema.
 *
 * Step references use order_index (which equals step.id in the frontend / "id" in GA JSON).
 * No database IDs — the refactoring API is a stateless document transformation.
 */

import type { components } from "@/api/schema";
import type { UndoRedoAction } from "@/stores/undoRedoStore/undoRedoAction";

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
import {
    InsertStepAction,
    LazyMutateStepAction,
    LazySetLabelAction,
    LazySetOutputLabelAction,
    RemoveStepAction,
    UpdateStepAction,
} from "./stepActions";
import { LazyMoveMultipleAction, LazySetValueAction } from "./workflowActions";

type RefactorAction = components["schemas"]["RefactorRequest"]["actions"][number];

export interface SerializationResult {
    actions: RefactorAction[];
    title: string;
    success: boolean;
    error?: string;
}

function stepRef(stepId: number): { order_index: number } {
    return { order_index: stepId };
}

function serializeLabelChange(action: LazySetLabelAction): SerializationResult {
    return {
        actions: [
            {
                action_type: "update_step_label" as const,
                step: stepRef(action.stepId),
                label: action.toValue ?? "",
            },
        ],
        title: `Set step label to "${action.toValue}"`,
        success: true,
    };
}

function serializeOutputLabelChange(action: LazySetOutputLabelAction): SerializationResult {
    // Find which output was changed by comparing fromValue and toValue arrays
    const toOutputs = action.toValue ?? [];
    const fromOutputs = action.fromValue ?? [];

    // Find the output that was added or changed
    const addedOrChanged = toOutputs.find(
        (to) => !fromOutputs.some((from) => from.output_name === to.output_name && from.label === to.label),
    );

    // Find the output that was removed
    const removed = fromOutputs.find((from) => !toOutputs.some((to) => to.output_name === from.output_name));

    if (addedOrChanged) {
        return {
            actions: [
                {
                    action_type: "update_output_label" as const,
                    output: { order_index: action.stepId, output_name: addedOrChanged.output_name },
                    output_label: addedOrChanged.label ?? "",
                },
            ],
            title: `Set output label to "${addedOrChanged.label}"`,
            success: true,
        };
    } else if (removed) {
        // Output was removed (label cleared)
        return {
            actions: [
                {
                    action_type: "update_output_label" as const,
                    output: { order_index: action.stepId, output_name: removed.output_name },
                    output_label: "",
                },
            ],
            title: `Clear output label "${removed.label}"`,
            success: true,
        };
    }

    return { actions: [], title: "output label change", success: false, error: "Could not determine changed output" };
}

function serializePositionChange(action: LazyMutateStepAction<"position">): SerializationResult {
    const position = action.toValue as { left: number; top: number } | undefined;
    if (!position) {
        return { actions: [], title: "move step", success: false, error: "No position value" };
    }
    return {
        actions: [
            {
                action_type: "update_step_position" as const,
                step: stepRef(action.stepId),
                position_absolute: { left: position.left, top: position.top },
            },
        ],
        title: "Move step",
        success: true,
    };
}

function serializeMoveMultiple(action: LazyMoveMultipleAction): SerializationResult {
    const { steps, comments } = action.getFinalPositions();
    const actions: RefactorAction[] = [];

    for (const [stepId, position] of steps) {
        actions.push({
            action_type: "update_step_position" as const,
            step: stepRef(stepId),
            position_absolute: { left: position.left, top: position.top },
        });
    }

    for (const [commentId, position] of comments) {
        actions.push({
            action_type: "update_comment_position" as const,
            comment: { comment_id: commentId },
            position: { left: position[0], top: position[1] },
        });
    }

    return {
        actions,
        title: `Move ${steps.size} step(s) and ${comments.size} comment(s)`,
        success: true,
    };
}

function serializeAddStep(action: InsertStepAction): SerializationResult {
    const { type, position } = action.stepData;
    return {
        actions: [
            {
                action_type: "add_step" as const,
                type: type as string,
                label: null,
                position: position ? { left: position.left, top: position.top } : null,
                tool_state: null,
            },
        ],
        title: `Add ${action.stepData.name}`,
        success: true,
    };
}

function serializeRemoveStep(action: RemoveStepAction): SerializationResult {
    return {
        actions: [
            {
                action_type: "remove_step" as const,
                step: stepRef(action.step.id),
            },
        ],
        title: `Remove step "${action.step.label ?? action.step.name}"`,
        success: true,
    };
}

/** Fields the refactor API's `update_step` action accepts. */
const REFACTORABLE_STEP_FIELDS = ["tool_state", "post_job_actions", "workflow_outputs", "when"] as const;

function serializeUpdateStep(action: UpdateStepAction): SerializationResult {
    const stepAction: Record<string, unknown> = {
        action_type: "update_step" as const,
        step: stepRef(action.stepId),
    };

    const { toPartial } = action;
    for (const field of REFACTORABLE_STEP_FIELDS) {
        if (toPartial[field] !== undefined) {
            stepAction[field] = toPartial[field];
        }
    }

    // If diff only contains derived/UI fields (inputs, outputs, config_form, errors),
    // nothing to send — backend recomputes them.
    if (!REFACTORABLE_STEP_FIELDS.some((k) => k in toPartial)) {
        return { actions: [], title: "Derived step update", success: true };
    }

    return {
        actions: [stepAction as RefactorAction],
        title: `Update step ${action.stepLabel}`,
        success: true,
    };
}

function serializeWorkflowMetadata(action: LazySetValueAction<unknown>): SerializationResult {
    switch (action.what) {
        case "name":
            return {
                actions: [{ action_type: "update_name" as const, name: action.toValue as string }],
                title: `Set workflow name to "${action.toValue}"`,
                success: true,
            };
        case "annotation":
            return {
                actions: [{ action_type: "update_annotation" as const, annotation: action.toValue as string }],
                title: `Set workflow annotation`,
                success: true,
            };
        case "license":
            return {
                actions: [{ action_type: "update_license" as const, license: action.toValue as string }],
                title: `Set license to "${action.toValue}"`,
                success: true,
            };
        case "creator":
            return {
                actions: [{ action_type: "update_creator" as const, creator: action.toValue as object }],
                title: `Set workflow creator`,
                success: true,
            };
        case "readme":
            return {
                actions: [{ action_type: "update_report" as const, report: { markdown: action.toValue as string } }],
                title: `Update workflow report`,
                success: true,
            };
        case "tags":
            return {
                actions: [{ action_type: "update_tags" as const, tags: action.toValue as string[] }],
                title: `Update tags`,
                success: true,
            };
        case "help":
            return {
                actions: [{ action_type: "update_help" as const, help: action.toValue as string }],
                title: `Update help`,
                success: true,
            };
        case "logoUrl":
            return {
                actions: [
                    { action_type: "update_logo_url" as const, logo_url: (action.toValue as string | null) ?? null },
                ],
                title: `Update logo URL`,
                success: true,
            };
        case "doi":
            return {
                actions: [{ action_type: "update_doi" as const, doi: action.toValue as string[] }],
                title: `Update DOI`,
                success: true,
            };
        default:
            return {
                actions: [],
                title: action.name,
                success: false,
                error: `Metadata type "${action.what}" not yet supported for serialization`,
            };
    }
}

function serializeAddComment(action: AddCommentAction): SerializationResult {
    const comment = action.comment;
    return {
        actions: [
            {
                action_type: "add_comment" as const,
                type: comment.type,
                position: { left: comment.position[0], top: comment.position[1] },
                size: { width: comment.size[0], height: comment.size[1] },
                color: comment.color,
                data: comment.data as Record<string, unknown>,
            },
        ],
        title: `Add ${comment.type} comment`,
        success: true,
    };
}

function serializeDeleteComment(action: DeleteCommentAction): SerializationResult {
    return {
        actions: [
            {
                action_type: "delete_comment" as const,
                comment: { comment_id: action.comment.id },
            },
        ],
        title: `Delete comment`,
        success: true,
    };
}

function serializeChangeCommentColor(action: ChangeColorAction): SerializationResult {
    return {
        actions: [
            {
                action_type: "update_comment_color" as const,
                comment: { comment_id: action.commentId },
                color: action.toColor,
            },
        ],
        title: `Change comment color`,
        success: true,
    };
}

function serializeChangeCommentData(action: LazyChangeDataAction): SerializationResult {
    return {
        actions: [
            {
                action_type: "update_comment_data" as const,
                comment: { comment_id: action.commentId },
                data: action.endData as Record<string, unknown>,
            },
        ],
        title: `Update comment data`,
        success: true,
    };
}

function serializeChangeCommentPosition(action: LazyChangePositionAction): SerializationResult {
    const position = action.endData;
    return {
        actions: [
            {
                action_type: "update_comment_position" as const,
                comment: { comment_id: action.commentId },
                position: { left: position[0], top: position[1] },
            },
        ],
        title: `Move comment`,
        success: true,
    };
}

function serializeChangeCommentSize(action: LazyChangeSizeAction): SerializationResult {
    const size = action.endData;
    return {
        actions: [
            {
                action_type: "update_comment_size" as const,
                comment: { comment_id: action.commentId },
                size: { width: size[0], height: size[1] },
            },
        ],
        title: `Resize comment`,
        success: true,
    };
}

function serializeRemoveAllFreehand(): SerializationResult {
    return {
        actions: [{ action_type: "remove_all_freehand_comments" as const }],
        title: `Remove all freehand comments`,
        success: true,
    };
}

/**
 * Shared serializer for connect/disconnect — identical structure, different action_type.
 *
 * Note: These action classes use callbacks for run/undo (not store references), so they
 * cannot be reconstructed from persisted JSON. Journal replay goes through the refactor
 * API directly — the serialized payload is the replay unit, not the frontend action.
 */
function serializeConnectionAction(
    action: ConnectStepAction | DisconnectStepAction,
    actionType: "connect" | "disconnect",
    title: string,
): SerializationResult {
    return {
        actions: [
            {
                action_type: actionType as const,
                input: {
                    order_index: action.connection.input.stepId,
                    input_name: action.connection.input.name,
                },
                output: {
                    order_index: action.connection.output.stepId,
                    output_name: action.connection.output.name,
                },
            },
        ],
        title,
        success: true,
    };
}

/**
 * Build a batch title from pending action serializations.
 * Joins individual titles with "; ", collapses adjacent duplicates, truncates at 200 chars.
 */
export function buildBatchTitle(serializations: SerializationResult[]): string {
    const titles: string[] = [];

    for (const s of serializations) {
        if (s.title && s.title !== titles[titles.length - 1]) {
            titles.push(s.title);
        }
    }

    const joined = titles.join("; ");

    if (joined.length <= 200) {
        return joined;
    }

    return joined.slice(0, 197) + "...";
}

/**
 * Serialize a frontend undo/redo action into backend refactor API action(s).
 *
 * Uses instanceof checks to route to specific serializers.
 * Returns { success: false } for unsupported action types.
 */
export function serializeAction(action: UndoRedoAction): SerializationResult {
    try {
        // Step actions — check specific subclasses before generic LazyMutateStepAction
        if (action instanceof LazySetLabelAction) {
            return serializeLabelChange(action);
        }
        if (action instanceof LazySetOutputLabelAction) {
            return serializeOutputLabelChange(action);
        }
        if (action instanceof LazyMutateStepAction && action.key === "position") {
            return serializePositionChange(action as LazyMutateStepAction<"position">);
        }
        if (action instanceof LazyMutateStepAction && action.key === "annotation") {
            return {
                actions: [
                    {
                        action_type: "update_step_annotation" as const,
                        step: stepRef(action.stepId),
                        annotation: (action.toValue as string) ?? "",
                    },
                ],
                title: "Update step annotation",
                success: true,
            };
        }
        if (action instanceof InsertStepAction) {
            return serializeAddStep(action);
        }
        if (action instanceof RemoveStepAction) {
            return serializeRemoveStep(action);
        }

        // Generic step update (SetDataAction extends UpdateStepAction, so this catches both)
        if (action instanceof UpdateStepAction) {
            return serializeUpdateStep(action);
        }

        // Workflow metadata
        if (action instanceof LazySetValueAction) {
            return serializeWorkflowMetadata(action);
        }

        // Move multiple (steps + comments)
        if (action instanceof LazyMoveMultipleAction) {
            return serializeMoveMultiple(action);
        }

        // Comment actions
        if (action instanceof AddCommentAction) {
            return serializeAddComment(action);
        }
        if (action instanceof DeleteCommentAction) {
            return serializeDeleteComment(action);
        }
        if (action instanceof ChangeColorAction) {
            return serializeChangeCommentColor(action);
        }
        if (action instanceof LazyChangeDataAction) {
            return serializeChangeCommentData(action);
        }
        if (action instanceof LazyChangePositionAction) {
            return serializeChangeCommentPosition(action);
        }
        if (action instanceof LazyChangeSizeAction) {
            return serializeChangeCommentSize(action);
        }
        if (action instanceof RemoveAllFreehandCommentsAction) {
            return serializeRemoveAllFreehand();
        }

        // Connection actions
        if (action instanceof ConnectStepAction) {
            return serializeConnectionAction(action, "connect", "Connect steps");
        }
        if (action instanceof DisconnectStepAction) {
            return serializeConnectionAction(action, "disconnect", "Disconnect steps");
        }

        // Unsupported action
        return {
            actions: [],
            title: action.name ?? "unknown action",
            success: false,
            error: "Action type not yet supported for serialization",
        };
    } catch (e) {
        return {
            actions: [],
            title: action.name ?? "unknown action",
            success: false,
            error: `Serialization error: ${e instanceof Error ? e.message : String(e)}`,
        };
    }
}
