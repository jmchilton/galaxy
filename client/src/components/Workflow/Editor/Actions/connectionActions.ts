import { UndoRedoAction } from "@/stores/undoRedoStore";
import type { Connection } from "@/stores/workflowStoreTypes";

/**
 * Connect two steps. Stores the connection data as a property for serialization.
 * Delegates actual connect/disconnect to callbacks from the Terminal layer
 * to preserve the Terminal's mapping and reactivity logic.
 */
export class ConnectStepAction extends UndoRedoAction {
    readonly connection: Connection;
    private connectFn: () => void;
    private disconnectFn: () => void;

    constructor(connection: Connection, connectFn: () => void, disconnectFn: () => void) {
        super();
        this.connection = connection;
        this.connectFn = connectFn;
        this.disconnectFn = disconnectFn;
    }

    get name() {
        return "connect steps";
    }

    get dataAttributes(): Record<string, string> {
        return { type: "connect" };
    }

    run() {
        this.connectFn();
    }

    undo() {
        this.disconnectFn();
    }
}

/**
 * Disconnect two steps. Stores the connection data as a property for serialization.
 * Delegates actual disconnect/reconnect to callbacks from the Terminal layer
 * to preserve the Terminal's resetMappingIfNeeded and reactivity logic.
 */
export class DisconnectStepAction extends UndoRedoAction {
    readonly connection: Connection;
    private disconnectFn: () => void;
    private reconnectFn: () => void;

    constructor(connection: Connection, disconnectFn: () => void, reconnectFn: () => void) {
        super();
        this.connection = connection;
        this.disconnectFn = disconnectFn;
        this.reconnectFn = reconnectFn;
    }

    get name() {
        return "disconnect steps";
    }

    get dataAttributes(): Record<string, string> {
        return { type: "disconnect" };
    }

    run() {
        this.disconnectFn();
    }

    undo() {
        this.reconnectFn();
    }
}
