import { nth } from "@tests/vitest/helpers";
import axios from "axios";
import flushPromises from "flush-promises";
import { createPinia, disposePinia, type Pinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";

import { useEntryPointStore } from "@/stores/entryPointStore";
import type { Tool } from "@/stores/toolStore";

import { makeCtx } from "../test-utils";
import { interactiveToolsProvider } from "./interactiveTools";
import { PALETTE_SCOPES } from "./scopes";

vi.mock("axios", () => ({
    default: {
        get: vi.fn(),
        delete: vi.fn(),
    },
}));

vi.mock("@/components/ToolsList/utilities", () => ({
    parseHelpForSummary: vi.fn(() => ""),
}));

// The toolbox response only needs the fields read by this provider and its store.
type ProviderTool = Pick<Tool, "id" | "name" | "description" | "model_class" | "panel_section_name">;
type EntryPoint = ReturnType<typeof useEntryPointStore>["entryPoints"][number];

const JUPYTER: ProviderTool = {
    id: "interactive_tool_jupyter_notebook/1.0",
    name: "Jupyter Notebook",
    description: "Interactive notebook environment",
    model_class: "InteractiveTool",
    panel_section_name: "Interactive tools",
};

const JUPYTER_OLD = { ...JUPYTER, id: "interactive_tool_jupyter_notebook/0.1" };

const RSTUDIO: ProviderTool = {
    id: "interactive_tool_rstudio/1.0",
    name: "RStudio",
    description: "R development environment",
    model_class: "InteractiveTool",
    panel_section_name: "Interactive tools",
};

const PLAIN_TOOL: ProviderTool = {
    id: "fastqc_id",
    name: "FastQC",
    description: "Read quality reports",
    model_class: "Tool",
    panel_section_name: "FASTQ Quality Control",
};

const ENTRY_POINT: EntryPoint = {
    model_class: "InteractiveToolEntryPoint",
    id: "ep1",
    job_id: "job1",
    name: "Jupyter Notebook",
    active: true,
    created_time: "2026-01-01T00:00:00",
    modified_time: "2026-01-01T00:00:00",
    output_datasets_ids: [],
};

const IT_SCOPE = PALETTE_SCOPES.find((scope) => scope.key === "it");

// the `it:` scope only exists where interactive tools are enabled
const itCtx = () => makeCtx({ config: { interactivetools_enable: true } });

/** `/api/tools` returns the toolbox, `/api/entry_points` the running tools */
function mockApi(entryPoints: EntryPoint[] = []) {
    vi.mocked(axios.get).mockImplementation(async (url: string) => {
        if (url.includes("entry_points")) {
            return { data: entryPoints };
        }
        return { data: [JUPYTER, JUPYTER_OLD, RSTUDIO, PLAIN_TOOL] };
    });
}

async function scopedSearch(query: string) {
    if (!IT_SCOPE) {
        throw new Error("Interactive-tools palette scope is missing");
    }
    const searchScoped = interactiveToolsProvider.searchScoped;
    if (!searchScoped) {
        throw new Error("Interactive-tools provider must support scoped search");
    }
    return searchScoped(IT_SCOPE, query, itCtx());
}

describe("interactiveToolsProvider", () => {
    let pinia: Pinia;

    beforeEach(() => {
        pinia = createPinia();
        setActivePinia(pinia);
        onTestFinished(() => disposePinia(pinia));
        vi.mocked(axios.get).mockReset();
        vi.mocked(axios.delete).mockReset();
    });

    it("lists only the latest version of the available interactive tools", async () => {
        mockApi();
        const sections = await scopedSearch("");

        expect(sections.map((section) => section.id)).toEqual(["available"]);
        const available = nth(sections, 0);
        expect(available.title).toBe("Available");
        expect(available.items.map((item) => item.id)).toEqual([
            "interactiveTools:interactive_tool_jupyter_notebook/1.0",
            "interactiveTools:interactive_tool_rstudio/1.0",
        ]);
        expect(nth(available.items, 0).to).toBe("/?tool_id=interactive_tool_jupyter_notebook%2F1.0&version=latest");
    });

    it("shows the running section first and links to the entry point display route", async () => {
        mockApi([ENTRY_POINT]);
        const sections = await scopedSearch("");

        expect(sections.map((section) => section.id)).toEqual(["running", "available"]);
        const running = nth(nth(sections, 0).items, 0);
        expect(running.title).toBe("Jupyter Notebook");
        expect(running.subtitle).toBe("Running");
        expect(running.to).toBe("/interactivetool_entry_points/ep1/display");
    });

    it("filters both sections client-side without extra requests", async () => {
        mockApi([ENTRY_POINT]);
        await scopedSearch("");
        vi.mocked(axios.get).mockClear();

        const sections = await scopedSearch("rstudio");
        expect(sections.map((section) => section.id)).toEqual(["available"]);
        expect(nth(sections, 0).items.map((item) => item.title)).toEqual(["RStudio"]);
        expect(axios.get).not.toHaveBeenCalled();
    });

    it("does not refetch the entry points of a user with nothing running", async () => {
        mockApi();
        await scopedSearch("");
        vi.mocked(axios.get).mockClear();

        await scopedSearch("r");
        await scopedSearch("rs");

        // an empty list is an answer, not a reason to ask the backend again
        expect(axios.get).not.toHaveBeenCalled();
    });

    it("stops a running tool through the secondary action", async () => {
        mockApi([ENTRY_POINT]);
        vi.mocked(axios.delete).mockResolvedValue({ data: {} });
        const sections = await scopedSearch("");
        const running = nth(nth(sections, 0).items, 0);

        const stopAction = running.secondaryAction;
        if (!stopAction?.run) {
            throw new Error("Running interactive tool must expose a runnable secondary action");
        }
        expect(stopAction.label).toBe("Stop");
        stopAction.run(itCtx());
        await flushPromises();

        expect(axios.delete).toHaveBeenCalledWith(expect.stringContaining("api/entry_points/ep1"));
        expect(useEntryPointStore(pinia).entryPoints).toEqual([]);
    });

    it("contributes nothing to the unscoped search", async () => {
        mockApi([ENTRY_POINT]);
        expect(await interactiveToolsProvider.search("jupyter", itCtx())).toEqual([]);
    });
});
