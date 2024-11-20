import { newWorker } from "@/utils/utils";

jest.mock("@/utils/utils");

type MessageHandler = (msg: string) => void;

class MockWorker {
    onmessage: MessageHandler;

    constructor() {
        this.onmessage = jest.fn();
    }

    postMessage(msg: string): void {
        this.onmessage(msg);
    }
}

export function setupMockWorker(): MockWorker {
    const worker = new MockWorker();
    (newWorker as jest.Mock).mockReturnValue(worker);
    return worker;
}
