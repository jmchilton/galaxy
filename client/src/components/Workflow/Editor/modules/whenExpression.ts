/**
 * Static analysis of workflow step `when` expressions.
 *
 * Galaxy addresses connected tool inputs by flat, pipe-prefixed connection names
 * (`cond|input1`), while a `when` expression walks nested tool state
 * (`inputs.cond.input1`). These helpers bridge the two representations so the editor can
 * reason about which inputs a gate reads and how the gate behaves when one of them is
 * absent.
 *
 * Nothing here executes user JavaScript. Expressions that are not structurally
 * recognized are reported as unknown, and callers are expected to resolve unknown
 * permissively: the runtime, not the editor, decides whether a step runs.
 */

type TokenType = "identifier" | "number" | "string" | "punct";

interface Token {
    type: TokenType;
    value: string;
}

export interface ReferenceAnalysis {
    /** Fully static `inputs` accesses, as path segments. */
    staticPaths: string[][];
    /** True when some `inputs` access could not be resolved statically. */
    hasDynamicInputsAccess: boolean;
}

export type NullBehavior = "false-when-null" | "true-when-null" | "unknown";

const PUNCTUATORS = ["===", "!==", "==", "!=", "&&", "||", "!", "(", ")", "[", "]", ".", ",", "?", ":"];

const UNKNOWN = Symbol("unknown");

type EvaluatedValue = typeof UNKNOWN | string | number | boolean | null | undefined;

/** Tokenize a JavaScript-ish expression, or return null when it cannot be scanned. */
function tokenize(expression: string): Token[] | null {
    const tokens: Token[] = [];
    let index = 0;

    while (index < expression.length) {
        const char = expression[index]!;

        if (/\s/.test(char)) {
            index++;
            continue;
        }

        if (char === "/" && expression[index + 1] === "/") {
            const newline = expression.indexOf("\n", index);
            index = newline === -1 ? expression.length : newline;
            continue;
        }

        if (char === "/" && expression[index + 1] === "*") {
            const end = expression.indexOf("*/", index + 2);
            if (end === -1) {
                return null;
            }
            index = end + 2;
            continue;
        }

        if (char === '"' || char === "'" || char === "`") {
            const literal = readStringLiteral(expression, index);
            if (!literal) {
                return null;
            }
            tokens.push({ type: "string", value: literal.value });
            index = literal.next;
            continue;
        }

        if (/[0-9]/.test(char)) {
            const match = /^[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?/.exec(expression.slice(index))!;
            tokens.push({ type: "number", value: match[0] });
            index += match[0].length;
            continue;
        }

        if (/[A-Za-z_$]/.test(char)) {
            const match = /^[A-Za-z_$][A-Za-z0-9_$]*/.exec(expression.slice(index))!;
            tokens.push({ type: "identifier", value: match[0] });
            index += match[0].length;
            continue;
        }

        const punctuator = PUNCTUATORS.find((candidate) => expression.startsWith(candidate, index));
        tokens.push({ type: "punct", value: punctuator ?? char });
        index += punctuator?.length ?? 1;
    }

    return tokens;
}

/** Read a quoted literal starting at `start`. Template literals keep their raw body. */
function readStringLiteral(expression: string, start: number): { value: string; next: number } | null {
    const quote = expression[start]!;
    let value = "";
    let index = start + 1;

    while (index < expression.length) {
        const char = expression[index]!;
        if (char === "\\") {
            value += expression[index + 1] ?? "";
            index += 2;
            continue;
        }
        if (char === quote) {
            return { value, next: index + 1 };
        }
        value += char;
        index++;
    }

    return null;
}

function isTemplateLiteral(expression: string): boolean {
    return expression.includes("`");
}

/**
 * Collect every `inputs` access in an expression.
 *
 * Recognizes dot access, chained bracket access with string literals, and mixtures of
 * the two. Anything else — a computed index, a bare `inputs` reference, a template
 * literal that might interpolate one — is reported through `hasDynamicInputsAccess`.
 */
export function analyzeInputReferences(expression: string): ReferenceAnalysis {
    const tokens = tokenize(expression);
    if (!tokens) {
        return { staticPaths: [], hasDynamicInputsAccess: true };
    }

    const analysis: ReferenceAnalysis = {
        staticPaths: [],
        hasDynamicInputsAccess: isTemplateLiteral(expression),
    };

    tokens.forEach((token, position) => {
        if (token.type !== "identifier" || token.value !== "inputs") {
            return;
        }
        if (tokens[position - 1]?.value === ".") {
            return;
        }
        const path = readAccessPath(tokens, position + 1);
        if (path.dynamic || path.segments.length === 0) {
            analysis.hasDynamicInputsAccess = true;
        }
        if (path.segments.length > 0) {
            analysis.staticPaths.push(path.segments);
        }
    });

    return analysis;
}

interface AccessPath {
    segments: string[];
    dynamic: boolean;
    next: number;
}

/** Walk the property access chain that follows an `inputs` token. */
function readAccessPath(tokens: Token[], start: number): AccessPath {
    const segments: string[] = [];
    let index = start;

    for (;;) {
        const token = tokens[index];
        if (token?.value === "." && tokens[index + 1]?.type === "identifier") {
            segments.push(tokens[index + 1]!.value);
            index += 2;
            continue;
        }
        if (token?.value === "[") {
            const inner = tokens[index + 1];
            if (inner?.type === "string" && tokens[index + 2]?.value === "]") {
                segments.push(inner.value);
                index += 3;
                continue;
            }
            return { segments, dynamic: true, next: index };
        }
        return { segments, dynamic: false, next: index };
    }
}

/** True when `targetPath` names the referenced access or an ancestor of it. */
function isPathPrefix(targetPath: string[], referencedPath: string[]): boolean {
    if (targetPath.length > referencedPath.length) {
        return false;
    }
    return targetPath.every((segment, position) => segment === referencedPath[position]);
}

function connectionPath(inputName: string): string[] {
    return inputName.split("|");
}

/**
 * True when the expression could read the named connection.
 *
 * Deliberately permissive: an expression the analyzer cannot resolve is treated as
 * referencing every candidate. Callers only ever ask about inputs that are already
 * connected, so an over-match shows a real edge while an under-match hides one.
 */
export function expressionReferencesInput(expression: string | undefined, inputName: string): boolean {
    if (!expression) {
        return false;
    }

    const targetPath = connectionPath(inputName);
    const references = analyzeInputReferences(expression);

    if (references.hasDynamicInputsAccess) {
        return true;
    }

    return references.staticPaths.some((referencedPath) => isPathPrefix(targetPath, referencedPath));
}

/** Strip the `$(...)` wrapper Galaxy `when` expressions carry. */
function expressionBody(expression: string): string | null {
    const trimmed = expression.trim();
    if (trimmed.startsWith("$(") && trimmed.endsWith(")")) {
        return trimmed.slice(2, -1);
    }
    return null;
}

/**
 * Decide how the expression behaves when the named connection carries no value.
 *
 * Evaluates a small, side-effect-free subset of JavaScript — literals, `inputs`
 * accesses, `!`, equality, and `&&`/`||` — with the target bound to `null` and every
 * other input left indeterminate. Anything outside that subset is `"unknown"`.
 */
export function classifyWhenInputIsNull(expression: string | undefined, inputName: string): NullBehavior {
    if (!expression) {
        return "unknown";
    }

    const body = expressionBody(expression);
    if (body === null || isTemplateLiteral(body)) {
        return "unknown";
    }

    const tokens = tokenize(body);
    if (!tokens || tokens.length === 0) {
        return "unknown";
    }

    const parser = new PresenceEvaluator(tokens, connectionPath(inputName));
    const value = parser.evaluate();
    if (value === UNKNOWN) {
        return "unknown";
    }

    return isTruthy(value) ? "true-when-null" : "false-when-null";
}

/**
 * True when the expression is safe to read as a presence guard for the named input.
 *
 * The step may still not run for other reasons; what matters to the editor is that the
 * expression is not known to run the step while the input is absent.
 */
export function expressionGuardsInputPresence(expression: string | undefined, inputName: string): boolean {
    if (!expressionReferencesInput(expression, inputName)) {
        return false;
    }

    return classifyWhenInputIsNull(expression, inputName) !== "true-when-null";
}

function isTruthy(value: Exclude<EvaluatedValue, typeof UNKNOWN>): boolean {
    return Boolean(value);
}

/**
 * Recursive-descent evaluator over the recognized expression subset.
 *
 * Throws {@link ParseFailure} on anything it does not model; callers map that to
 * "unknown" rather than to a verdict.
 */
class ParseFailure extends Error {}

class PresenceEvaluator {
    private tokens: Token[];
    private targetPath: string[];
    private position = 0;

    constructor(tokens: Token[], targetPath: string[]) {
        this.tokens = tokens;
        this.targetPath = targetPath;
    }

    evaluate(): EvaluatedValue {
        try {
            const value = this.parseOr();
            if (this.position !== this.tokens.length) {
                return UNKNOWN;
            }
            return value;
        } catch (error) {
            if (error instanceof ParseFailure) {
                return UNKNOWN;
            }
            throw error;
        }
    }

    private peek(): Token | undefined {
        return this.tokens[this.position];
    }

    private consume(value: string): boolean {
        if (this.peek()?.value === value) {
            this.position++;
            return true;
        }
        return false;
    }

    private parseOr(): EvaluatedValue {
        let left = this.parseAnd();
        while (this.consume("||")) {
            const right = this.parseAnd();
            left = combineOr(left, right);
        }
        return left;
    }

    private parseAnd(): EvaluatedValue {
        let left = this.parseEquality();
        while (this.consume("&&")) {
            const right = this.parseEquality();
            left = combineAnd(left, right);
        }
        return left;
    }

    private parseEquality(): EvaluatedValue {
        let left = this.parseUnary();
        for (;;) {
            const operator = this.peek()?.value;
            if (operator !== "===" && operator !== "!==" && operator !== "==" && operator !== "!=") {
                return left;
            }
            this.position++;
            const right = this.parseUnary();
            left = compare(operator, left, right);
        }
    }

    private parseUnary(): EvaluatedValue {
        if (this.consume("!")) {
            const value = this.parseUnary();
            return value === UNKNOWN ? UNKNOWN : !isTruthy(value);
        }
        return this.parsePrimary();
    }

    private parsePrimary(): EvaluatedValue {
        const token = this.peek();
        if (!token) {
            throw new ParseFailure("unexpected end of expression");
        }

        if (this.consume("(")) {
            const value = this.parseOr();
            if (!this.consume(")")) {
                throw new ParseFailure("unbalanced parentheses");
            }
            return value;
        }

        if (token.type === "string") {
            this.position++;
            return token.value;
        }

        if (token.type === "number") {
            this.position++;
            return Number(token.value);
        }

        if (token.type === "identifier") {
            return this.parseIdentifier(token);
        }

        throw new ParseFailure(`unrecognized token ${token.value}`);
    }

    private parseIdentifier(token: Token): EvaluatedValue {
        this.position++;

        switch (token.value) {
            case "null":
                return null;
            case "undefined":
                return undefined;
            case "true":
                return true;
            case "false":
                return false;
        }

        if (token.value !== "inputs") {
            throw new ParseFailure(`unrecognized identifier ${token.value}`);
        }

        const path = readAccessPath(this.tokens, this.position);
        this.position = path.next;
        if (path.dynamic) {
            throw new ParseFailure("dynamic inputs access");
        }
        return isPathPrefix(this.targetPath, path.segments) ? null : UNKNOWN;
    }
}

function combineAnd(left: EvaluatedValue, right: EvaluatedValue): EvaluatedValue {
    if (left !== UNKNOWN && !isTruthy(left)) {
        return false;
    }
    if (right !== UNKNOWN && !isTruthy(right)) {
        return false;
    }
    if (left === UNKNOWN || right === UNKNOWN) {
        return UNKNOWN;
    }
    return true;
}

function combineOr(left: EvaluatedValue, right: EvaluatedValue): EvaluatedValue {
    if (left !== UNKNOWN && isTruthy(left)) {
        return true;
    }
    if (right !== UNKNOWN && isTruthy(right)) {
        return true;
    }
    if (left === UNKNOWN || right === UNKNOWN) {
        return UNKNOWN;
    }
    return false;
}

function compare(operator: string, left: EvaluatedValue, right: EvaluatedValue): EvaluatedValue {
    if (left === UNKNOWN || right === UNKNOWN) {
        return UNKNOWN;
    }

    const strict = left === right;
    const loose = isNullish(left) && isNullish(right) ? true : strict;

    switch (operator) {
        case "===":
            return strict;
        case "!==":
            return !strict;
        case "==":
            return loose;
        default:
            return !loose;
    }
}

function isNullish(value: Exclude<EvaluatedValue, typeof UNKNOWN>): boolean {
    return value === null || value === undefined;
}
