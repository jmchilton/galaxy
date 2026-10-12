import type { Meta, StoryObj } from "@storybook/vue3-vite";
import { withCurrentUser } from "@tests/test-data/currentUser";
import { http as transport, HttpResponse } from "msw";

import { http } from "@/api/client/__mocks__/http";
import { typesAndMappingHandler } from "@/components/Datatypes/test_fixtures";
import type { PredictedToolChild } from "@/components/Workflow/Editor/modules/utilities";

import ToolRecommendation from "./ToolRecommendation.vue";

// The shipped cat1 tool inherits its output format; Cut1 accepts text and is named "Cut".
const PREDICTIONS = {
    current_tool: "cat1",
    predicted_data: {
        name: "Concatenate multiple datasets or collections",
        is_deprecated: false,
        o_extensions: ["input"],
        children: [
            { name: "Cut", tool_id: "Cut1", tool_score: 0.9, i_extensions: ["txt"] },
        ] satisfies PredictedToolChild[],
    },
};

const meta = {
    title: "ToolRecommendation",
    component: ToolRecommendation,
    args: { toolId: "cat1" },
    decorators: [withCurrentUser()],
    parameters: {
        msw: {
            handlers: {
                // This legacy endpoint is not part of Galaxy's OpenAPI schema.
                predictions: http.untyped.post("/api/workflows/get_tool_predictions", async ({ request }) => {
                    const payload = (await request.json()) as { tool_sequence?: string };
                    if (payload.tool_sequence === PREDICTIONS.current_tool) {
                        return HttpResponse.json(PREDICTIONS);
                    }
                }),
                datatypes: typesAndMappingHandler,
            },
        },
    },
} satisfies Meta<typeof ToolRecommendation>;
export default meta;
type Story = StoryObj<typeof meta>;

/** Galaxy recommends Cut after concatenating datasets; its text input accepts the inherited output type. */
export const CompatibleTools: Story = {};

/** The prediction request fails before the datatype compatibility check can begin. */
export const PredictionNetworkFailure: Story = {
    parameters: {
        msw: {
            handlers: {
                predictions: transport.post("/api/workflows/get_tool_predictions", () => HttpResponse.error()),
            },
        },
    },
};

/** Predictions arrive, but the datatype registry cannot be loaded to check compatibility. */
export const DatatypesNetworkFailure: Story = {
    parameters: {
        msw: {
            handlers: {
                datatypes: transport.get("/api/datatypes/types_and_mapping", () => HttpResponse.error()),
            },
        },
    },
};

/** An instance with no configured prediction model returns JSON null and offers no recommendations. */
export const NoPredictionModel: Story = {
    parameters: {
        msw: {
            handlers: {
                predictions: http.untyped.post("/api/workflows/get_tool_predictions", () => HttpResponse.json(null)),
            },
        },
    },
};
