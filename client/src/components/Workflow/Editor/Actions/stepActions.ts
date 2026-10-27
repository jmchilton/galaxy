import { toRaw } from "vue";

import { replaceLabel } from "@/components/Markdown/parse";
import { autoLayout } from "@/components/Workflow/Editor/modules/layout";
import { terminalFactory } from "@/components/Workflow/Editor/modules/terminals";
import { useToast } from "@/composables/toast";
import { useWorkflowStores } from "@/composables/workflowStores";
import { useDatatypesMapperStore } from "@/stores/datatypesMapperStore";
import { useRefreshFromStore } from "@/stores/refreshFromStore";
import { LazyUndoRedoAction, UndoRedoAction, type UndoRedoStore, useUndoRedoStore } from "@/stores/undoRedoStore";
import { getConnectionId, type WorkflowConnectionStore } from "@/stores/workflowConnectionStore";
import { useWorkflowCommentStore } from "@/stores/workflowEditorCommentStore";
import type { WorkflowStateStore } from "@/stores/workflowEditorStateStore";
import {
    getCombinedStepInputs,
    type NewStep,
    normalizeConnectionOutputLinks,
    type Step,
    useWorkflowStepStore,
    type WorkflowStepStore,
} from "@/stores/workflowStepStore";
import type { Connection } from "@/stores/workflowStoreTypes";
import { assertDefined } from "@/utils/assertions";
import { cloneRaw } from "@/utils/toRawDeep";

import { cloneStepWithUniqueLabel, getLabelSet } from "./cloneStep";

type WorkflowStores = ReturnType<typeof useWorkflowStores>;

export class LazyMutateStepAction<K extends keyof Step> extends LazyUndoRedoAction {
    key: K;
    fromValue: Step[K];
    toValue: Step[K];
    stepId;
    stepStore;
    stepLabel;
    onUndoRedo?: () => void;

    get name() {
        return this.internalName ?? `modify step ${this.stepLabel}`;
    }

    set name(name: string | undefined) {
        this.internalName = name;
    }

    constructor(stepStore: WorkflowStepStore, stepId: number, key: K, fromValue: Step[K], toValue: Step[K]) {
        super();
        this.stepStore = stepStore;
        this.stepId = stepId;
        this.key = key;
        this.fromValue = fromValue;
        this.toValue = toValue;

        this.stepLabel = `${stepId + 1}`;
        const step = this.stepStore.getStep(stepId);

        if (step) {
            this.stepLabel = `"${stepId + 1}: ${step.label ?? step.name}"`;
        }
    }

    queued() {
        this.stepStore.updateStepValue(this.stepId, this.key, this.toValue);
    }

    changeValue(value: Step[K]) {
        this.toValue = value;
        this.stepStore.updateStepValue(this.stepId, this.key, this.toValue);
    }

    undo() {
        this.stepStore.updateStepValue(this.stepId, this.key, this.fromValue);
        this.onUndoRedo?.();
    }

    redo() {
        this.stepStore.updateStepValue(this.stepId, this.key, this.toValue);
        this.onUndoRedo?.();
    }
}

function onLabelSet(
    classInstance: LazySetLabelAction | LazySetOutputLabelAction,
    from: string | null | undefined,
    to: string | null | undefined,
) {
    const markdown = classInstance.stateStore.report.markdown ?? "";
    const newMarkdown = replaceLabel(markdown, classInstance.labelType, from, to);

    if (markdown !== newMarkdown) {
        classInstance.stateStore.report.markdown = newMarkdown;
        classInstance.success(
            `${classInstance.labelTypeTitle} label updated from "${from}" to "${to}" in workflow report.`,
        );
    }
}

export class LazySetLabelAction extends LazyMutateStepAction<"label"> {
    labelType: "input" | "step";
    labelTypeTitle: "Input" | "Step";
    stateStore: WorkflowStateStore;
    success;

    constructor(
        stepStore: WorkflowStepStore,
        stateStore: WorkflowStateStore,
        stepId: number,
        fromValue: Step["label"],
        toValue: Step["label"],
    ) {
        super(stepStore, stepId, "label", fromValue, toValue);

        const step = this.stepStore.getStep(this.stepId);
        assertDefined(step);

        const stepType = step.type;
        const isInput = ["data_input", "data_collection_input", "parameter_input"].indexOf(stepType) >= 0;
        this.labelType = isInput ? "input" : "step";
        this.labelTypeTitle = isInput ? "Input" : "Step";
        this.stateStore = stateStore;
        this.success = useToast().success;
    }

    run() {
        onLabelSet(this, this.fromValue, this.toValue);
    }

    undo() {
        super.undo();
        onLabelSet(this, this.toValue, this.fromValue);
    }

    redo() {
        super.redo();
        this.run();
    }
}

export class LazySetOutputLabelAction extends LazyMutateStepAction<"workflow_outputs"> {
    success;
    fromLabel;
    toLabel;
    stateStore;
    labelType = "output" as const;
    labelTypeTitle = "Output" as const;

    constructor(
        stepStore: WorkflowStepStore,
        stateStore: WorkflowStateStore,
        stepId: number,
        fromValue: string | null,
        toValue: string | null,
        toOutputs: Step["workflow_outputs"],
    ) {
        const step = stepStore.getStep(stepId);
        assertDefined(step);
        const fromOutputs = cloneRaw(step.workflow_outputs);

        super(stepStore, stepId, "workflow_outputs", fromOutputs, cloneRaw(toOutputs));

        this.fromLabel = fromValue;
        this.toLabel = toValue;
        this.stateStore = stateStore;
        this.success = useToast().success;
    }

    run() {
        onLabelSet(this, this.fromLabel, this.toLabel);
    }

    undo() {
        super.undo();
        onLabelSet(this, this.toLabel, this.fromLabel);
    }

    redo() {
        this.run();
        super.redo();
    }
}

export class UpdateStepAction extends UndoRedoAction {
    stepStore;
    stateStore;
    stepId;
    fromPartial;
    toPartial;
    stepLabel;
    onUndoRedo?: () => void;

    get name() {
        return this.internalName ?? `modify step ${this.stepLabel}`;
    }

    set name(name: string | undefined) {
        this.internalName = name;
    }

    constructor(
        stepStore: WorkflowStepStore,
        stateStore: WorkflowStateStore,
        stepId: number,
        fromPartial: Partial<Step>,
        toPartial: Partial<Step>,
    ) {
        super();
        this.stepStore = stepStore;
        this.stateStore = stateStore;
        this.stepId = stepId;
        this.fromPartial = fromPartial;
        this.toPartial = toPartial;

        this.stepLabel = `${stepId + 1}`;
        const step = this.stepStore.getStep(stepId);

        if (step) {
            this.stepLabel = `"${stepId + 1}: ${step.label ?? step.name}"`;
        }
    }

    isEmpty() {
        return Object.keys(this.fromPartial).length === 0;
    }

    run() {
        const step = this.stepStore.getStep(this.stepId);
        assertDefined(step);
        this.stepStore.updateStep({ ...step, ...this.toPartial });
    }

    undo() {
        const step = this.stepStore.getStep(this.stepId);
        assertDefined(step);
        this.stepStore.updateStep({ ...step, ...this.fromPartial });
        this.onUndoRedo?.();
    }

    redo() {
        this.run();
        this.onUndoRedo?.();
    }
}

/**
 * Updates a step's `when` or `input_connections`, dropping each connection left without a port.
 * A connection loses its port when the new `input_connections` omits it or the new `when` no longer reads it.
 */
export class UpdateStepConnectionsAction extends UpdateStepAction {
    stores;
    droppedConnections: Connection[];
    mapOverBefore?: Pick<WorkflowStepStore, "stepMapOver" | "stepInputMapOver">;

    constructor(stores: WorkflowStores, stepId: number, fromPartial: Partial<Step>, toPartial: Partial<Step>) {
        const step = stores.stepStore.getStep(stepId);
        assertDefined(step);
        const orphanedPorts = stores.stepStore.extraInputsRemovedBy(stepId, toPartial);
        if (orphanedPorts.length > 0) {
            const inputConnections = { ...(toPartial.input_connections ?? step.input_connections) };
            orphanedPorts.forEach((name) => delete inputConnections[name]);
            toPartial = { ...toPartial, input_connections: inputConnections };
            fromPartial = { ...fromPartial, input_connections: cloneRaw(step.input_connections) };
        }
        super(stores.stepStore, stores.stateStore, stepId, fromPartial, toPartial);
        this.stores = stores;
        const kept = toPartial.input_connections;
        const dropped = kept
            ? stores.connectionStore
                  .getConnectionsForStep(stepId)
                  .filter(
                      (connection) =>
                          connection.input.stepId === stepId &&
                          !normalizeConnectionOutputLinks(kept[connection.input.name]).some(
                              (link) =>
                                  link.id === connection.output.stepId && link.output_name === connection.output.name,
                          ),
                  )
            : [];
        this.droppedConnections = cloneRaw(dropped);
    }

    run() {
        if (this.droppedConnections.length > 0) {
            const { stepMapOver, stepInputMapOver } = this.stores.stepStore;
            this.mapOverBefore = {
                stepMapOver: { ...stepMapOver },
                stepInputMapOver: Object.fromEntries(
                    Object.entries(stepInputMapOver).map(([stepId, inputs]) => [stepId, { ...inputs }]),
                ),
            };
        }
        this.droppedConnections.forEach((connection) => this.dropConnection(connection));
        super.run();
    }

    undo() {
        // Re-adding rewrites the links, so the step's own fields are restored last.
        this.droppedConnections.forEach((connection) =>
            this.stores.connectionStore.addConnection(cloneRaw(connection)),
        );
        super.undo();
        if (this.mapOverBefore) {
            this.stores.stepStore.stepMapOver = this.mapOverBefore.stepMapOver;
            this.stores.stepStore.stepInputMapOver = this.mapOverBefore.stepInputMapOver;
        }
    }

    /** Drops through the input terminal, as a manual disconnect does, so map-over is reset too. */
    private dropConnection(connection: Connection) {
        const step = this.stores.stepStore.getStep(this.stepId);
        const port =
            step &&
            getCombinedStepInputs(step, this.stores.stepStore).find((input) => input.name === connection.input.name);
        const datatypesMapper = useDatatypesMapperStore().datatypesMapper;
        if (port && datatypesMapper) {
            terminalFactory(this.stepId, port, datatypesMapper, this.stores).dropConnection(connection);
        } else {
            this.stores.connectionStore.removeConnection(getConnectionId(connection));
        }
    }
}

export class SetDataAction extends UpdateStepAction {
    constructor(stepStore: WorkflowStepStore, stateStore: WorkflowStateStore, from: Step, to: Step) {
        const fromPartial: Partial<Step> = {};
        const toPartial: Partial<Step> = {};

        Object.entries(from).forEach(([key, value]) => {
            const otherValue = to[key as keyof Step] as any;

            if (JSON.stringify(value) !== JSON.stringify(otherValue)) {
                fromPartial[key as keyof Step] = cloneRaw(value);
                toPartial[key as keyof Step] = cloneRaw(otherValue);
            }
        });

        super(stepStore, stateStore, from.id, fromPartial, toPartial);
    }
}

export type InsertStepData = {
    contentId: Parameters<WorkflowStepStore["insertNewStep"]>[0];
    name: Parameters<WorkflowStepStore["insertNewStep"]>[1];
    type: Parameters<WorkflowStepStore["insertNewStep"]>[2];
    position: Parameters<WorkflowStepStore["insertNewStep"]>[3];
};

export class InsertStepAction extends UndoRedoAction {
    stepStore;
    stateStore;
    stepData;
    updateStepData?: Step;
    stepId?: number;
    newStepData?: Step;

    constructor(stepStore: WorkflowStepStore, stateStore: WorkflowStateStore, stepData: InsertStepData) {
        super();
        this.stepStore = stepStore;
        this.stateStore = stateStore;
        this.stepData = stepData;
    }

    get name() {
        return `insert ${this.stepData.name}`;
    }

    get dataAttributes(): Record<string, string> {
        return {
            type: "step-insert",
            "step-type": this.stepData.type as string,
        };
    }

    stepDataToTuple() {
        return Object.values(this.stepData) as Parameters<WorkflowStepStore["insertNewStep"]>;
    }

    getNewStepData() {
        assertDefined(this.newStepData);
        return this.newStepData;
    }

    run() {
        this.newStepData = this.stepStore.insertNewStep(...this.stepDataToTuple());
        this.stepId = this.newStepData.id;

        if (this.updateStepData) {
            this.stepStore.updateStep(this.updateStepData);
            this.stepId = this.updateStepData.id;
        }
    }

    undo() {
        assertDefined(this.stepId);
        this.stepStore.removeStep(this.stepId);
    }

    redo() {
        this.run();
        assertDefined(this.stepId);
    }
}

export class RemoveStepAction extends UndoRedoAction {
    stepStore;
    stateStore;
    connectionStore;
    step: Step;
    connections: Connection[];

    constructor(
        stepStore: WorkflowStepStore,
        stateStore: WorkflowStateStore,
        connectionStore: WorkflowConnectionStore,
        step: Step,
    ) {
        super();
        this.stepStore = stepStore;
        this.stateStore = stateStore;
        this.connectionStore = connectionStore;
        this.step = cloneRaw(step);
        const connections = this.connectionStore.getConnectionsForStep(this.step.id);
        // Deep clone to avoid proxy issues
        this.connections = JSON.parse(JSON.stringify(toRaw(connections)));
    }

    get name() {
        return `remove step "${this.step.id} ${this.step.label ?? this.step.name}"`;
    }

    run() {
        this.stepStore.removeStep(this.step.id);
        this.stateStore.activeNodeId = null;
        this.stateStore.hasChanges = true;
    }

    undo() {
        this.stepStore.addStep(cloneRaw(this.step), false, false);
        this.connections.forEach((connection) => {
            // Ensure connection is a plain object
            const plainConnection = JSON.parse(JSON.stringify(connection));
            this.connectionStore.addConnection(plainConnection);
        });
        this.stateStore.hasChanges = true;
    }
}

export class CopyStepAction extends UndoRedoAction {
    stepStore;
    stateStore;
    step: NewStep;
    stepLabel;
    stepId?: number;
    onUndoRedo?: () => void;

    constructor(stepStore: WorkflowStepStore, stateStore: WorkflowStateStore, step: Step) {
        super();
        this.stepStore = stepStore;
        this.stateStore = stateStore;

        const labelSet = getLabelSet(stepStore);
        this.stepLabel = `${step.id + 1}: ${step.label ?? step.name}`;
        this.step = cloneStepWithUniqueLabel(step, labelSet);
        delete this.step.id;
        // A cloned step must get its own uuid; keeping the source step's uuid
        // produces a "Duplicate step UUID" error when saving the workflow.
        delete this.step.uuid;
        // `cloneStepWithUniqueLabel` deep-clones `workflow_outputs` too, so each output's
        // uuid must be stripped the same way, or saving fails with "Duplicate workflow
        // output UUID" instead.
        this.step.workflow_outputs?.forEach((workflowOutput) => delete workflowOutput.uuid);
    }

    get name() {
        return `duplicate step "${this.stepLabel}"`;
    }

    run() {
        const newStep = this.stepStore.addStep(cloneRaw(this.step));
        this.stepId = newStep.id;
        this.stateStore.hasChanges = true;
    }

    undo() {
        assertDefined(this.stepId);
        this.stepStore.removeStep(this.stepId);
    }
}

export class ToggleStepSelectedAction extends UndoRedoAction {
    stateStore;
    stepStore;
    stepId;
    toggleTo: boolean;
    stepLabel;

    constructor(stateStore: WorkflowStateStore, stepStore: WorkflowStepStore, stepId: number) {
        super();

        this.stateStore = stateStore;
        this.stepStore = stepStore;
        this.stepId = stepId;
        this.toggleTo = !this.stateStore.getStepMultiSelected(stepId);

        const label = this.stepStore.getStep(this.stepId)?.label;
        this.stepLabel = label ?? `${this.stepId + 1}`;
    }

    get name() {
        if (this.toggleTo === true) {
            return `add step ${this.stepLabel} to selection`;
        } else {
            return `remove step ${this.stepLabel} from selection`;
        }
    }

    run() {
        this.stateStore.setStepMultiSelected(this.stepId, this.toggleTo);
    }

    undo() {
        this.stateStore.setStepMultiSelected(this.stepId, !this.toggleTo);
    }
}

interface Positions {
    steps: { id: string; x: number; y: number }[];
    comments: { id: string; x: number; y: number; w: number; h: number }[];
}

export class AutoLayoutAction extends UndoRedoAction {
    stepStore;
    commentStore;
    positions: Positions;
    oldPositions: Positions;
    workflowId;
    ran;

    constructor(workflowId: string) {
        super();

        this.workflowId = workflowId;
        this.stepStore = useWorkflowStepStore(workflowId);
        this.commentStore = useWorkflowCommentStore(workflowId);

        this.positions = {
            steps: [],
            comments: [],
        };

        this.oldPositions = {
            steps: [],
            comments: [],
        };

        this.ran = false;
    }

    get name() {
        return "auto layout";
    }

    private mapPositionsToStore(positions: Positions) {
        positions.steps.map((p) => {
            const step = this.stepStore.steps[p.id];
            if (step) {
                this.stepStore.updateStep({
                    ...step,
                    position: {
                        top: p.y,
                        left: p.x,
                    },
                });
            }
        });

        positions.comments.map((c) => {
            const id = parseInt(c.id, 10);
            const comment = this.commentStore.commentsRecord[id];
            if (comment) {
                this.commentStore.changePosition(id, [c.x, c.y]);
                this.commentStore.changeSize(id, [c.w, c.h]);
            }
        });
    }

    async run() {
        this.ran = true;

        this.oldPositions.steps = Object.values(this.stepStore.steps).map((step) => ({
            id: `${step.id}`,
            x: step.position?.left ?? 0,
            y: step.position?.top ?? 0,
        }));

        this.oldPositions.comments = this.commentStore.comments.map((comment) => ({
            id: `${comment.id}`,
            x: comment.position[0],
            y: comment.position[1],
            w: comment.size[0],
            h: comment.size[1],
        }));

        this.commentStore.resolveCommentsInFrames();
        this.commentStore.resolveStepsInFrames();

        const newPositions = await autoLayout(this.workflowId, this.stepStore.steps, this.commentStore.comments);

        assertDefined(newPositions);

        this.positions = newPositions as Positions;

        if (this.ran) {
            this.mapPositionsToStore(this.positions);
            useUndoRedoStore(this.workflowId).changeId += 1;
        }
    }

    undo() {
        this.ran = false;
        this.mapPositionsToStore(this.oldPositions);
    }

    redo() {
        this.mapPositionsToStore(this.positions);
    }
}

export function useStepActions(
    stepStore: WorkflowStepStore,
    undoRedoStore: UndoRedoStore,
    stateStore: WorkflowStateStore,
    connectionStore: WorkflowConnectionStore,
    workflowId: string,
) {
    /**
     * If the pending action is a `LazyMutateStepAction` and matches the step id and field key, returns it.
     * Otherwise returns `null`
     */
    function actionForIdAndKey(id: number, key: keyof Step) {
        const pendingAction = undoRedoStore.pendingLazyAction;

        if (pendingAction instanceof LazyMutateStepAction && pendingAction.stepId === id && pendingAction.key === key) {
            return pendingAction;
        } else {
            return null;
        }
    }

    interface ChangeValueOrCreateActionOptions<K extends keyof Step> {
        step: Step;
        key: K;
        value: Step[K];
        name?: string;
        actionConstructor?: () => LazyMutateStepAction<K>;
        keepActionAlive?: boolean;
        timeout?: number;
    }

    /**
     * Mutates a queued lazy action, if a matching one exists,
     * otherwise creates a new lazy action ans queues it.
     */
    function changeValueOrCreateAction<K extends keyof Step>(
        options: ChangeValueOrCreateActionOptions<K>,
    ): InstanceType<typeof LazyMutateStepAction<K>> {
        const { step, key, value, name, keepActionAlive, timeout } = options;
        const actionForKey = actionForIdAndKey(step.id, key);

        if (actionForKey) {
            actionForKey.changeValue(value);

            if (keepActionAlive) {
                undoRedoStore.setLazyActionTimeout(timeout);
            }

            if (name) {
                actionForKey.name = name;
            }

            return actionForKey;
        } else {
            const actionConstructor =
                options.actionConstructor ??
                (() => new LazyMutateStepAction(stepStore, step.id, key, step[key], value));

            const action = actionConstructor();

            if (name) {
                action.name = name;
            }

            undoRedoStore.applyLazyAction(action, timeout);

            action.onUndoRedo = () => {
                stateStore.hasChanges = true;
            };

            return action;
        }
    }

    function setPosition(step: Step, position: NonNullable<Step["position"]>) {
        changeValueOrCreateAction({
            step,
            key: "position",
            value: position,
            name: `move step "${step.id + 1}: ${step.label ?? step.name}"`,
        });
    }

    function setAnnotation(step: Step, annotation: Step["annotation"]) {
        changeValueOrCreateAction({
            step,
            key: "annotation",
            value: annotation,
            name: `edit annotation of step "${step.id + 1}: ${step.label ?? step.name}"`,
        });
    }

    function setOutputLabel(
        step: Step,
        workflowOutputs: Step["workflow_outputs"],
        fromLabel: string | null,
        toLabel: string | null,
    ) {
        const actionConstructor = () =>
            new LazySetOutputLabelAction(stepStore, stateStore, step.id, fromLabel, toLabel, workflowOutputs);

        changeValueOrCreateAction({
            step,
            key: "workflow_outputs",
            value: workflowOutputs,
            name: `edit output label of step "${step.id + 1}: ${step.label ?? step.name}"`,
            actionConstructor,
            keepActionAlive: true,
            timeout: 2000,
        });
    }

    function setLabel(step: Step, label: Step["label"]) {
        const actionConstructor = () => new LazySetLabelAction(stepStore, stateStore, step.id, step.label, label);
        changeValueOrCreateAction({
            step,
            key: "label",
            value: label,
            name: `change label of step ${step.id + 1} to "${label}"`,
            actionConstructor,
            keepActionAlive: true,
            timeout: 2000,
        });
    }

    const { refresh } = useRefreshFromStore();

    function setData(from: Step, to: Step) {
        const action = new SetDataAction(stepStore, stateStore, from, to);

        if (!action.isEmpty()) {
            action.onUndoRedo = () => {
                stateStore.hasChanges = true;
                refresh();
            };
            undoRedoStore.applyAction(action);
        }
    }

    function removeStep(step: Step) {
        const action = new RemoveStepAction(stepStore, stateStore, connectionStore, step);
        undoRedoStore.applyAction(action);
    }

    function updateStep(id: number, toPartial: Partial<Step>) {
        const fromStep = stepStore.getStep(id);
        assertDefined(fromStep);
        const fromPartial: Partial<Step> = {};

        Object.keys(toPartial).forEach((key) => {
            fromPartial[key as keyof Step] = cloneRaw(fromStep[key as keyof Step]) as any;
        });

        const action =
            "when" in toPartial || "input_connections" in toPartial
                ? new UpdateStepConnectionsAction(useWorkflowStores(workflowId), id, fromPartial, toPartial)
                : new UpdateStepAction(stepStore, stateStore, id, fromPartial, toPartial);

        if (!action.isEmpty()) {
            action.onUndoRedo = () => {
                stateStore.hasChanges = true;
                refresh();
            };
            undoRedoStore.applyAction(action);
        }
    }

    function copyStep(step: Step) {
        const action = new CopyStepAction(stepStore, stateStore, step);
        undoRedoStore.applyAction(action);
    }

    return {
        setPosition,
        setAnnotation,
        setLabel,
        setData,
        setOutputLabel,
        removeStep,
        updateStep,
        copyStep,
    };
}
