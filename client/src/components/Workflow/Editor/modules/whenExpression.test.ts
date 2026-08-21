import { describe, expect, it } from "vitest";

import {
    analyzeInputReferences,
    classifyWhenInputIsNull,
    expressionGuardsInputPresence,
    expressionReferencesInput,
    presenceGateExpression,
} from "./whenExpression";

describe("analyzeInputReferences", () => {
    it.each([
        ["$(inputs.cond.input1)", [["cond", "input1"]]],
        ['$(inputs["cond"]["input1"])', [["cond", "input1"]]],
        ['$(inputs.cond["input1"])', [["cond", "input1"]]],
        ["$(inputs['cond'].input1)", [["cond", "input1"]]],
        ['$(inputs["cond|input1"])', [["cond|input1"]]],
        ["$(inputs.a && inputs.b)", [["a"], ["b"]]],
    ])("reads static access paths out of %s", (expression, expected) => {
        const analysis = analyzeInputReferences(expression);
        expect(analysis.staticPaths).toEqual(expected);
        expect(analysis.hasDynamicInputsAccess).toBe(false);
    });

    it("ignores inputs mentioned inside string literals", () => {
        const analysis = analyzeInputReferences('$(inputs.a === "inputs.b")');
        expect(analysis.staticPaths).toEqual([["a"]]);
        expect(analysis.hasDynamicInputsAccess).toBe(false);
    });

    it("ignores inputs mentioned inside comments", () => {
        const analysis = analyzeInputReferences("$(inputs.a /* inputs.b */ !== null) // inputs.c");
        expect(analysis.staticPaths).toEqual([["a"]]);
        expect(analysis.hasDynamicInputsAccess).toBe(false);
    });

    it("does not treat a nested inputs property as a root access", () => {
        const analysis = analyzeInputReferences("$(inputs.inputs.a)");
        expect(analysis.staticPaths).toEqual([["inputs", "a"]]);
    });

    it.each([
        ["a computed index", "$(inputs[name])"],
        ["a bare reference", "$(Object.keys(inputs).length)"],
        ["a template literal", "$(`${inputs.a}` !== null)"],
    ])("reports %s as dynamic", (_label, expression) => {
        expect(analyzeInputReferences(expression).hasDynamicInputsAccess).toBe(true);
    });

    it("keeps the static half of a partly dynamic access", () => {
        const analysis = analyzeInputReferences("$(inputs.cond[name])");
        expect(analysis.staticPaths).toEqual([["cond"]]);
        expect(analysis.hasDynamicInputsAccess).toBe(true);
    });
});

describe("expressionReferencesInput", () => {
    it("returns false without an expression", () => {
        expect(expressionReferencesInput(undefined, "input1")).toBe(false);
        expect(expressionReferencesInput("", "input1")).toBe(false);
    });

    it("matches a nested connection name against a nested access path", () => {
        expect(expressionReferencesInput("$(inputs.cond.input1 !== null)", "cond|input1")).toBe(true);
    });

    it("matches an ancestor connection name", () => {
        expect(expressionReferencesInput("$(inputs.cond.input1 !== null)", "cond")).toBe(true);
    });

    it("compares whole segments rather than substrings", () => {
        expect(expressionReferencesInput("$(inputs.cond.input10 !== null)", "cond|input1")).toBe(false);
        expect(expressionReferencesInput("$(inputs.input10 !== null)", "input1")).toBe(false);
    });

    it("does not match the flat pipe-prefixed spelling", () => {
        expect(expressionReferencesInput('$(inputs["cond|input1"] !== null)', "cond|input1")).toBe(false);
    });

    it("matches every candidate when access cannot be resolved statically", () => {
        expect(expressionReferencesInput("$(inputs[name] !== null)", "cond|input1")).toBe(true);
    });
});

describe("classifyWhenInputIsNull", () => {
    it.each([
        ["$(inputs.cond.input1 !== null)", "false-when-null"],
        ['$(inputs["cond"]["input1"] != null)', "false-when-null"],
        ["$(!!inputs.cond.input1)", "false-when-null"],
        ["$(inputs.cond.input1 !== null && inputs.force)", "false-when-null"],
        ["$(inputs.cond.input1 === null)", "true-when-null"],
        ["$(inputs.cond.input1 == null)", "true-when-null"],
        ["$(!inputs.cond.input1)", "true-when-null"],
        ["$(inputs.cond.input1 === null || inputs.force)", "true-when-null"],
        ["$(helper(inputs.cond.input1))", "unknown"],
        ["$(inputs[name] !== null)", "unknown"],
        ["$(inputs.cond.input1 !== null || inputs.force)", "unknown"],
    ])("classifies %s", (expression, expected) => {
        expect(classifyWhenInputIsNull(expression, "cond|input1")).toBe(expected);
    });

    it("is unknown for an expression that is not a $() body", () => {
        expect(classifyWhenInputIsNull("${ return inputs.cond.input1 !== null; }", "cond|input1")).toBe("unknown");
    });

    it("leaves other inputs indeterminate", () => {
        expect(classifyWhenInputIsNull("$(inputs.other !== null)", "cond|input1")).toBe("unknown");
    });

    it("leaves a property read on the target indeterminate", () => {
        // If `reference` is null this throws rather than evaluating either way.
        expect(classifyWhenInputIsNull('$(inputs.reference.format != "bwa_mem2_index")', "reference")).toBe("unknown");
        expect(classifyWhenInputIsNull('$(inputs.reference.format === "x")', "reference")).toBe("unknown");
    });
});

describe("expressionGuardsInputPresence", () => {
    it.each([
        ["$(inputs.cond.input1 !== null)", true],
        ['$(inputs["cond"]["input1"] != null)', true],
        ["$(!!inputs.cond.input1)", true],
        ["$(inputs.cond.input1 === null)", false],
        ["$(inputs.cond.input1 === null || inputs.force)", false],
        ["$(helper(inputs.cond.input1))", true],
        ["$(inputs[name] !== null)", true],
        ["$(inputs.cond.input10 !== null)", false],
        ['$(inputs["cond|input1"] !== null)', false],
        ["$(inputs.other !== null)", false],
    ])("decides %s", (expression, expected) => {
        expect(expressionGuardsInputPresence(expression, "cond|input1")).toBe(expected);
    });

    it("returns false without an expression", () => {
        expect(expressionGuardsInputPresence(undefined, "cond|input1")).toBe(false);
    });

    it("allows a gate that reads a property of the input", () => {
        expect(expressionGuardsInputPresence('$(inputs.reference.format != "bwa_mem2_index")', "reference")).toBe(true);
    });
});

describe("presenceGateExpression", () => {
    it.each([
        ["input1", "$(inputs.input1 !== null)"],
        ["cond|input1", "$(inputs.cond.input1 !== null)"],
        ["segment-with-dashes", '$(inputs["segment-with-dashes"] !== null)'],
        ["cond|has-dash", '$(inputs.cond["has-dash"] !== null)'],
        ["0|input1", '$(inputs["0"].input1 !== null)'],
    ])("spells %s", (inputName, expected) => {
        expect(presenceGateExpression(inputName)).toBe(expected);
    });

    it.each(["input1", "cond|input1", "segment-with-dashes", "cond|has-dash", "0|input1"])(
        "generates a gate the analyzer reads back for %s",
        (inputName) => {
            const expression = presenceGateExpression(inputName);
            expect(expressionReferencesInput(expression, inputName)).toBe(true);
            expect(classifyWhenInputIsNull(expression, inputName)).toBe("false-when-null");
            expect(expressionGuardsInputPresence(expression, inputName)).toBe(true);
        },
    );
});

describe("analyzer soundness", () => {
    it("does not decide a cross-type loose comparison", () => {
        // JS says 1 == "1", so this expression is true when the input is absent.
        expect(classifyWhenInputIsNull("$(1 == '1' && inputs.cond.input1 === null)", "cond|input1")).toBe("unknown");
        expect(expressionGuardsInputPresence('$(inputs.a !== null || 0 == "")', "a")).toBe(true);
        expect(classifyWhenInputIsNull('$(inputs.a !== null || 0 == "")', "a")).toBe("unknown");
    });

    it("still decides same-type loose comparisons", () => {
        expect(classifyWhenInputIsNull("$(inputs.a == null)", "a")).toBe("true-when-null");
        expect(classifyWhenInputIsNull("$(inputs.a != null)", "a")).toBe("false-when-null");
    });

    it("yields the surviving operand of a logical expression", () => {
        expect(classifyWhenInputIsNull("$((inputs.a || inputs.a) !== null)", "a")).toBe("false-when-null");
        expect(classifyWhenInputIsNull("$((inputs.a && inputs.a) === null)", "a")).toBe("true-when-null");
    });

    it("survives an expression deep enough to exhaust the stack", () => {
        const deep = `$(${"(".repeat(20000)}inputs.a${")".repeat(20000)} !== null)`;
        expect(() => classifyWhenInputIsNull(deep, "a")).not.toThrow();
        expect(classifyWhenInputIsNull(deep, "a")).toBe("unknown");
        expect(() => expressionGuardsInputPresence(deep, "a")).not.toThrow();
    });

    it("reads through optional chaining", () => {
        expect(expressionReferencesInput("$(inputs.cond?.input1 !== null)", "cond|input1")).toBe(true);
        expect(classifyWhenInputIsNull("$(inputs.cond?.input1 === null)", "cond|input1")).toBe("true-when-null");
        expect(analyzeInputReferences("$(inputs.cond?.input1)").staticPaths).toEqual([["cond", "input1"]]);
    });

    it("does not mistake a regex body for real code", () => {
        const analysis = analyzeInputReferences("$(/inputs.zzz/.test(inputs.a))");
        expect(analysis.staticPaths).toEqual([]);
        expect(analysis.hasDynamicInputsAccess).toBe(true);
    });

    it("is not fooled by a token after the closing parenthesis", () => {
        expect(classifyWhenInputIsNull("$(inputs.a === null);", "a")).toBe("true-when-null");
        expect(classifyWhenInputIsNull("$(inputs.a === null) // trailing", "a")).toBe("true-when-null");
        expect(expressionGuardsInputPresence("$(inputs.a === null);", "a")).toBe(false);
    });

    it("still refuses to parse a genuinely truncated expression", () => {
        expect(classifyWhenInputIsNull("$(inputs.a === null", "a")).toBe("unknown");
        expect(classifyWhenInputIsNull("$(inputs.a === null)) extra", "a")).toBe("unknown");
    });
});
