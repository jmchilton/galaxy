import { describe, expect, it } from "vitest";

import { generateApiSchema } from "../../scripts/generate-api-schema.mjs";

function body(name) {
    return { content: { "application/json": { schema: { $ref: `#/components/schemas/${name}` } } } };
}

const document = {
    openapi: "3.1.0",
    info: { title: "test", version: "1" },
    paths: {
        "/things": {
            post: {
                requestBody: body("Payload"),
                responses: { 200: { description: "ok", ...body("Result") } },
            },
        },
    },
    components: {
        schemas: {
            Payload: {
                type: "object",
                properties: {
                    flag: { type: "boolean", default: false },
                    nested: { $ref: "#/components/schemas/Nested" },
                    shared: { allOf: [{ $ref: "#/components/schemas/Shared" }] },
                    "a/b": { type: "integer", default: 1 },
                    "x~y": { type: "integer", default: 1 },
                },
                required: ["a/b", "x~y"],
            },
            Nested: { type: "object", properties: { depth: { type: "integer", default: 0 } } },
            Shared: { type: "object", properties: { label: { type: "string", default: "x" } } },
            Result: {
                type: "object",
                properties: {
                    shared: { type: "array", items: { $ref: "#/components/schemas/Shared" } },
                    count: { type: "integer", default: 0 },
                },
            },
        },
    },
};

function schemaBlock(output, name) {
    return output.match(new RegExp(`\\n {8}${name}: \\{\\n([\\s\\S]*?)\\n {8}\\};`))[1];
}

describe("generate-api-schema", () => {
    it("makes defaulted properties of request-only schemas optional", async () => {
        const output = await generateApiSchema(document);
        expect(schemaBlock(output, "Payload")).toContain("flag?: boolean;");
        expect(schemaBlock(output, "Nested")).toContain("depth?: number;");
    });

    it("keeps defaulted properties required in schemas reachable from responses", async () => {
        const output = await generateApiSchema(document);
        expect(schemaBlock(output, "Shared")).toContain("label: string;");
        expect(schemaBlock(output, "Result")).toContain("count: number;");
    });

    it("keeps explicitly required properties required, whatever their name", async () => {
        const payload = schemaBlock(await generateApiSchema(document), "Payload");
        expect(payload).toContain('"a/b": number;');
        expect(payload).toContain('"x~y": number;');
    });
});
