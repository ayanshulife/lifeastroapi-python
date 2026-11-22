// Generator of the Python report templates (src/lifeastroapi/pdf/_templates/).
//
// The Node SDK's TypeScript templates (lifeastroapi-node/src/pdf/) are the one source of
// the report HTML. This script walks their syntax trees and writes the same program in
// Python, on the small runtime in src/lifeastroapi/pdf/_js.py that supplies the JavaScript
// semantics (undefined, truthiness, number to string, toFixed, key order, regex classes).
// Label tables, CSS and text are therefore copied exactly, never retyped.
//
//   node scripts/generate_pdf.mjs       then: node scripts/pdf_goldens.mjs && pytest
//
// It supports only the syntax and built-ins the templates use, and stops with the file and
// line on anything else, so a template change can never be translated silently wrong.
//
// Environment:
//   LIFEASTRO_NODE_SDK   path to the Node SDK repo (default ../lifeastroapi-node); needs its
//                        dev dependencies (typescript).
//   RUFF                 the ruff that formats the output (default .venv/bin/ruff).
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const NODE_SDK = resolve(process.env.LIFEASTRO_NODE_SDK ?? join(ROOT, "..", "lifeastroapi-node"));
const SRC = join(NODE_SDK, "src", "pdf");
const OUT = join(ROOT, "src", "lifeastroapi", "pdf", "_templates");
const ts = createRequire(join(NODE_SDK, "package.json"))("typescript");
const K = ts.SyntaxKind;

const SOURCES = [
  join(SRC, "shared.ts"),
  join(SRC, "locales.ts"),
  join(SRC, "colors.ts"),
  ...readdirSync(join(SRC, "templates"))
    .filter((f) => f.endsWith(".ts"))
    .sort()
    .map((f) => join(SRC, "templates", f)),
];
const program = ts.createProgram(SOURCES, {
  target: ts.ScriptTarget.ES2022,
  module: ts.ModuleKind.NodeNext,
  moduleResolution: ts.ModuleResolutionKind.NodeNext,
  strict: true,
  noEmit: true,
  skipLibCheck: true,
});
const checker = program.getTypeChecker();

/** Functions of shared.ts that always return a string, so `${...}` needs no conversion. */
const RETURNS_STRING = new Set(["esc", "escBody", "escList", "humanize", "cssString"]);
/** Names a Python identifier must not take. */
const RESERVED = new Set(
  (
    "False None True and as assert async await break class continue def del elif else except finally for from " +
    "global if import in is lambda nonlocal not or pass raise return try while with yield match case " +
    "js Any range len list dict str int float bool type id max min sum map filter set get all any next hash " +
    "input object open print slice property format bytes iter zip vars dir help license copyright credits"
  ).split(" "),
);
/** JavaScript's `\s` inside a character class; `js.Regex` expands it. */
const SPACE = "<WS>";
/**
 * Patterns that retry at every position of a run and so are quadratic on a long one (seconds on
 * a 100 KB string), each with a linear pattern that finds the same matches in a replace-all.
 * The leftmost match always starts where its run starts, unless the search resumed inside the
 * run: only the arrow pattern can end in white space, so only it may also start after one.
 */
const RUN_START = new Map([
  [String.raw`\s*(?:\u27f6|\u21d2|\u2192|->|=>)\s*`, (p) => p.replace(`[${SPACE}]*`, `(?:(?<![${SPACE}])[${SPACE}]*)?`)],
  [String.raw`\s+,`, (p) => `(?<![${SPACE}])${p}`],
  [String.raw`\s*,\s*([)\]])`, (p) => `(?<![${SPACE}])${p}`],
  [String.raw`[ \t]+\n`, (p) => `(?<![ \\t])${p}`],
  [
    String.raw`[^\u0964]*\u0907\u0928\s*\u0924\u0940\u0928\s*\u0938\u094d\u0924\u0930(?:\u094b\u0902|\u093e\u0902)[\s\S]*?\u0926\u0947\u0916[^\u0964]*\u0964`,
    (p) => `(?<![^\\u0964])${p}`,
  ],
]);
/** Characters written as escapes so that they are visible in the Python source. */
const INVISIBLE = /[\u00a0\u00ad\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u202a-\u202e\u2060\ufeff\u007f-\u009f]/g;

const moduleName = (file) => basename(file, ".ts").replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
const safeName = (name) => (RESERVED.has(name) ? `${name}_` : name);
const indent = (lines) => lines.map((line) => (line ? `    ${line}` : line));
const quote = (text) =>
  JSON.stringify(text).replace(INVISIBLE, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);

/** A string as Python source; text with line breaks gets one literal per line. */
function pyString(text) {
  const lines = text.match(/[^\n]*\n|[^\n]+/g) ?? [];
  return lines.length > 1 ? `(\n${lines.map(quote).join("\n")}\n)` : quote(text);
}

function unwrap(node) {
  while (
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isNonNullExpression(node) ||
    ts.isSatisfiesExpression(node) ||
    ts.isTypeAssertionExpression(node)
  ) {
    node = node.expression;
  }
  return node;
}

const isFunction = (node) => ts.isArrowFunction(node) || ts.isFunctionExpression(node);
const isBuiltinMember = (name) =>
  (checker.getSymbolAtLocation(name)?.declarations ?? []).some((d) => d.getSourceFile().isDeclarationFile);
const isGlobal = (node, name) => ts.isIdentifier(node) && node.text === name && isBuiltinMember(node);

const COMPARE = new Map([
  [K.LessThanToken, "lt"],
  [K.LessThanEqualsToken, "le"],
  [K.GreaterThanToken, "gt"],
  [K.GreaterThanEqualsToken, "ge"],
]);
const ARITHMETIC = new Map([
  [K.MinusToken, "sub"],
  [K.AsteriskToken, "mul"],
  [K.SlashToken, "div"],
  [K.PercentToken, "mod"],
]);
/** `Math` functions, and how many arguments each is given. */
const MATH = {
  cos: ["cos", 1, 1],
  sin: ["sin", 1, 1],
  sqrt: ["sqrt", 1, 1],
  floor: ["floor", 1, 1],
  round: ["round_", 1, 1],
  pow: ["pow_", 2, 2],
  min: ["min_", 1, Infinity],
  max: ["max_", 1, Infinity],
};
const DATE_METHODS = {
  getTime: "get_time",
  getUTCFullYear: "utc_year",
  getUTCMonth: "utc_month",
  getUTCDate: "utc_date",
  getUTCHours: "utc_hours",
  getUTCMinutes: "utc_minutes",
};

/** One Python scope: the module, a def or a lambda. */
class Scope {
  constructor(parent) {
    this.parent = parent;
    this.taken = new Set();
    this.outer = new Set(); // names assigned here that an outer scope owns
  }
  has(name) {
    return this.taken.has(name) || (this.parent?.has(name) ?? false);
  }
}

class Module {
  constructor(sourceFile) {
    this.file = sourceFile;
    this.root = new Scope(null);
    this.names = new Map();
    this.imports = new Map();
    this.used = new Set();
    this.regexes = new Map();
    this.serial = 0;
  }

  fail(node, message) {
    const { line } = this.file.getLineAndCharacterOfPosition(node.getStart());
    throw new Error(`${this.file.fileName}:${line + 1}: ${message}: ${node.getText().slice(0, 140)}`);
  }

  fresh(prefix) {
    this.serial += 1;
    return `_${prefix}${this.serial}`;
  }

  // Python has function scope only and closures see the variable, not a copy, so every
  // declaration gets a name that no enclosing scope uses.
  declare(ident, scope) {
    const symbol = checker.getSymbolAtLocation(ident);
    if (!symbol) this.fail(ident, "no symbol");
    const known = this.names.get(symbol);
    if (known?.scope === scope) return known.name;
    const base = safeName(ident.text);
    let name = base;
    for (let n = 2; scope.has(name); n++) name = `${base}_${n}`;
    scope.taken.add(name);
    this.names.set(symbol, { name, scope });
    return name;
  }

  lookup(ident) {
    const symbol = ts.isShorthandPropertyAssignment(ident.parent)
      ? checker.getShorthandAssignmentValueSymbol(ident.parent)
      : checker.getSymbolAtLocation(ident);
    const found = symbol && this.names.get(symbol);
    if (!found) this.fail(ident, "unknown name");
    this.used.add(found.name);
    return found;
  }

  // -- regular expressions ---------------------------------------------------

  translateRegex(node, source) {
    let out = "";
    let inClass = false;
    for (let i = 0; i < source.length; i++) {
      const c = source[i];
      if (!inClass && source.startsWith("[\\s\\S]", i)) {
        out += "(?s:.)";
        i += 5;
      } else if (c === "\\") {
        const next = source[++i];
        if (next === "s") out += inClass ? SPACE : `[${SPACE}]`;
        else if (next === "S") {
          if (inClass) this.fail(node, "\\S inside a character class");
          out += `[^${SPACE}]`;
        } else if (next === "/") out += "/";
        else if ("dDwWbnrtu.[](){}*+?^$|\\-".includes(next)) out += c + next;
        else this.fail(node, `regex escape \\${next}`);
      } else if (inClass) {
        if (c === "]") inClass = false;
        out += c === "[" ? "\\[" : c;
      } else if (c === "[") {
        inClass = true;
        out += c;
      } else if (c === ".") out += "[^\\n\\r\\u2028\\u2029]";
      else if (c === "$") out += "\\Z";
      else if (c === "(" && source[i + 1] === "?" && source[i + 2] !== ":") this.fail(node, "regex group");
      else out += c;
    }
    return out;
  }

  regex(node) {
    const end = node.text.lastIndexOf("/");
    const flags = node.text.slice(end + 1);
    if (/[^gi]/.test(flags)) this.fail(node, "regex flag");
    if (!this.regexes.has(node.text)) {
      const source = node.text.slice(1, end);
      const escaped = source.replace(/[^\x00-\x7f]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, "0")}`);
      const runStart = flags.includes("g") ? RUN_START.get(escaped) : undefined;
      if (runStart) this.runStarts = (this.runStarts ?? 0) + 1;
      const translated = this.translateRegex(node, source);
      let args = quote(runStart ? runStart(translated) : translated);
      if (flags.includes("i")) args += ", ignore_case=True";
      if (flags.includes("g")) args += ", all_=True";
      this.regexes.set(node.text, { name: `_RE${this.regexes.size + 1}`, args });
    }
    return this.regexes.get(node.text).name;
  }

  // A global regex keeps `lastIndex` between exec() / test() calls, which the runtime does not.
  statelessRegex(node) {
    const target = unwrap(node);
    const declared = ts.isIdentifier(target) ? checker.getSymbolAtLocation(target)?.valueDeclaration : undefined;
    const literal = declared?.initializer ? unwrap(declared.initializer) : target;
    if (ts.isRegularExpressionLiteral(literal) && /\/[a-z]*g[a-z]*$/.test(literal.text)) {
      this.fail(node, "exec / test on a global regex");
    }
  }

  // -- functions -------------------------------------------------------------

  /** A lambda, or a def placed before the current statement (`pre`) and its name. */
  func(node, scope, pre, { name = null, variadic = false } = {}) {
    const inner = new Scope(scope);
    const params = [];
    const prologue = [];
    const defaults = [];
    let hasRest = false;
    for (const p of node.parameters) {
      if (ts.isIdentifier(p.name)) {
        const local = this.declare(p.name, inner);
        if (p.dotDotDotToken) {
          hasRest = true;
          params.push({ local, rest: true });
        } else {
          params.push({ local, optional: !!(p.questionToken || p.initializer) });
          if (p.initializer) defaults.push([local, p.initializer]);
        }
      } else {
        const local = this.fresh("arg");
        params.push({ local });
        prologue.push(...this.destructure(p.name, local, inner));
      }
    }
    if (variadic && !hasRest) params.push({ local: "_rest", rest: true });

    const body = [...prologue];
    for (const [local, init] of defaults) {
      const before = [];
      const value = this.expr(init, inner, before);
      body.push(`if ${local} is js.UNDEF:`, ...indent([...before, `${local} = ${value}`]));
    }
    if (ts.isBlock(node.body)) {
      body.push(...this.block(node.body.statements, inner));
      if (!this.terminates(node.body.statements)) body.push("return js.UNDEF");
    } else {
      const before = [];
      const value = this.expr(node.body, inner, before);
      if (!name && !body.length && !before.length && !inner.outer.size) {
        const list = params.map(
          (p) => (p.rest ? "*" : "") + p.local + (p.optional ? "=js.UNDEF" : ""),
        );
        return `(lambda${list.length ? ` ${list.join(", ")}` : ""}: ${value})`;
      }
      body.push(...before, `return ${value}`);
    }
    const defName = name ?? this.fresh("fn");
    const list = params.map(
      (p) => `${p.rest ? "*" : ""}${p.local}: Any${p.optional ? " = js.UNDEF" : ""}`,
    );
    pre.push(`def ${defName}(${list.join(", ")}) -> Any:`);
    for (const owned of [...inner.outer].sort()) {
      pre.push(`    ${this.root.taken.has(owned) ? "global" : "nonlocal"} ${owned}`);
    }
    pre.push(...indent(body));
    return defName;
  }

  destructure(pattern, source, scope) {
    if (ts.isArrayBindingPattern(pattern)) {
      const targets = pattern.elements.map((element) => {
        if (ts.isOmittedExpression(element)) return this.fresh("skip");
        if (!ts.isIdentifier(element.name) || element.initializer || element.dotDotDotToken) {
          this.fail(element, "array pattern");
        }
        return this.declare(element.name, scope);
      });
      return [`[${targets.join(", ")}] = js.unpack(${source}, ${targets.length})`];
    }
    const from = this.fresh("from");
    const lines = [`${from}: Any = ${source}`];
    for (const element of pattern.elements) {
      if (!ts.isIdentifier(element.name) || element.dotDotDotToken) this.fail(element, "object pattern");
      const local = this.declare(element.name, scope);
      const key = (element.propertyName ?? element.name).text;
      lines.push(`${local}: Any = js.get(${from}, ${quote(key)})`);
      if (element.initializer) {
        const before = [];
        const value = this.expr(element.initializer, scope, before);
        lines.push(`if ${local} is js.UNDEF:`, ...indent([...before, `${local} = ${value}`]));
      }
    }
    return lines;
  }

  /** A callback as Python, with the number of arguments it takes. */
  callback(node, scope, pre, supplied) {
    const fn = unwrap(node);
    if (isFunction(fn)) {
      const wanted = fn.parameters.length;
      if (wanted > supplied) this.fail(fn, "callback parameters");
      return { code: this.func(fn, scope, pre, { variadic: wanted === 0 }), arity: Math.max(wanted, 1) };
    }
    for (const [js, py] of [["String", "js.s"], ["Boolean", "js.truthy"], ["Number", "js.to_number"]]) {
      if (isGlobal(fn, js)) return { code: py, arity: 1 };
    }
    const signature = checker.getTypeAtLocation(fn).getCallSignatures()[0];
    if (!signature) this.fail(fn, "callback");
    const arity = Math.min(signature.parameters.length, supplied);
    if (arity < 1) this.fail(fn, "callback without parameters");
    return { code: this.expr(fn, scope, pre), arity };
  }

  // -- expressions -----------------------------------------------------------

  isString(node) {
    node = unwrap(node);
    if (ts.isStringLiteralLike(node) || ts.isTemplateExpression(node)) return true;
    if (ts.isTypeOfExpression(node)) return true;
    if (ts.isConditionalExpression(node)) return this.isString(node.whenTrue) && this.isString(node.whenFalse);
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === K.PlusToken) {
      return this.isString(node.left) || this.isString(node.right);
    }
    if (ts.isCallExpression(node)) {
      const callee = unwrap(node.expression);
      if (ts.isIdentifier(callee)) {
        if (isGlobal(callee, "String")) return true;
        if (!RETURNS_STRING.has(callee.text)) return false;
        let symbol = checker.getSymbolAtLocation(callee);
        if (symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol);
        return symbol.declarations[0].getSourceFile().fileName.endsWith("/shared.ts");
      }
      if (ts.isPropertyAccessExpression(callee) && isBuiltinMember(callee.name)) {
        return ["join", "replace", "trim", "toFixed", "padStart", "toLowerCase"].includes(callee.name.text);
      }
    }
    return false;
  }

  isBoolean(node) {
    node = unwrap(node);
    if (node.kind === K.TrueKeyword || node.kind === K.FalseKeyword) return true;
    if (ts.isPrefixUnaryExpression(node)) return node.operator === K.ExclamationToken;
    if (ts.isBinaryExpression(node)) {
      const op = node.operatorToken.kind;
      if (COMPARE.has(op) || op === K.EqualsEqualsEqualsToken || op === K.ExclamationEqualsEqualsToken) return true;
      if (op === K.InKeyword) return true;
      if (op === K.AmpersandAmpersandToken || op === K.BarBarToken) {
        return this.isBoolean(node.left) && this.isBoolean(node.right);
      }
    }
    if (ts.isCallExpression(node)) {
      const callee = unwrap(node.expression);
      if (isGlobal(callee, "Boolean")) return true;
      if (ts.isPropertyAccessExpression(callee) && isBuiltinMember(callee.name)) {
        if (["isArray", "isNaN", "includes", "some", "startsWith", "endsWith", "test"].includes(callee.name.text)) return true;
        return this.isHasOwnCall(node);
      }
    }
    return false;
  }

  /** `Object.prototype.hasOwnProperty.call(table, key)`. */
  isHasOwnCall(node) {
    const callee = unwrap(node.expression);
    return (
      node.arguments.length === 2 &&
      ts.isPropertyAccessExpression(callee) &&
      callee.name.text === "call" &&
      callee.expression.getText() === "Object.prototype.hasOwnProperty"
    );
  }

  /** An expression used as a condition: a Python bool with JavaScript's truthiness. */
  cond(node, scope, pre) {
    const n = unwrap(node);
    if (ts.isPrefixUnaryExpression(n) && n.operator === K.ExclamationToken) {
      return `(not ${this.cond(n.operand, scope, pre)})`;
    }
    if (ts.isBinaryExpression(n)) {
      const op = n.operatorToken.kind;
      if (op === K.AmpersandAmpersandToken || op === K.BarBarToken) {
        const word = op === K.BarBarToken ? "or" : "and";
        return `(${this.cond(n.left, scope, pre)} ${word} ${this.cond(n.right, scope, pre)})`;
      }
    }
    if (ts.isCallExpression(n) && isGlobal(unwrap(n.expression), "Boolean")) {
      return this.cond(n.arguments[0], scope, pre);
    }
    if (this.isBoolean(n)) return this.expr(n, scope, pre);
    return `js.truthy(${this.expr(n, scope, pre)})`;
  }

  asString(node, scope, pre) {
    const code = this.expr(node, scope, pre);
    return this.isString(node) ? code : `js.s(${code})`;
  }

  /** Can this be evaluated early, where JavaScript would have skipped it? */
  isPlain(node) {
    node = unwrap(node);
    if (ts.isStringLiteralLike(node) || ts.isNumericLiteral(node) || ts.isIdentifier(node)) return true;
    if (node.kind === K.NullKeyword || node.kind === K.TrueKeyword || node.kind === K.FalseKeyword) return true;
    if (ts.isArrayLiteralExpression(node)) return node.elements.length === 0;
    return ts.isObjectLiteralExpression(node) && node.properties.length === 0;
  }

  expr(original, scope, pre) {
    const node = unwrap(original);
    const ex = (child) => this.expr(child, scope, pre);

    if (ts.isStringLiteralLike(node)) return pyString(node.text);
    if (ts.isNumericLiteral(node)) return String(Number(node.text));
    if (node.kind === K.TrueKeyword) return "True";
    if (node.kind === K.FalseKeyword) return "False";
    if (node.kind === K.NullKeyword) return "None";
    if (ts.isRegularExpressionLiteral(node)) return this.regex(node);
    if (ts.isIdentifier(node)) {
      return node.text === "undefined" ? "js.UNDEF" : this.lookup(node).name;
    }
    if (ts.isTemplateExpression(node)) {
      const parts = node.head.text ? [pyString(node.head.text)] : [];
      for (const span of node.templateSpans) {
        parts.push(this.asString(span.expression, scope, pre));
        if (span.literal.text) parts.push(pyString(span.literal.text));
      }
      return parts.length === 1 ? parts[0] : `(\n${parts.join("\n+ ")}\n)`;
    }
    if (ts.isArrayLiteralExpression(node)) {
      const items = node.elements.map((e) =>
        ts.isSpreadElement(e) ? `*js.iterate(${ex(e.expression)})` : ex(e),
      );
      return `[${items.join(", ")}]`;
    }
    if (ts.isObjectLiteralExpression(node)) {
      const items = node.properties.map((p) => {
        if (ts.isSpreadAssignment(p)) return `**${ex(p.expression)}`;
        if (ts.isShorthandPropertyAssignment(p)) return `${quote(p.name.text)}: ${this.lookup(p.name).name}`;
        if (!ts.isPropertyAssignment(p) || ts.isComputedPropertyName(p.name)) this.fail(p, "object member");
        const key = ts.isNumericLiteral(p.name) ? String(Number(p.name.text)) : p.name.text;
        const value = unwrap(p.initializer);
        // TypeScript lets a function in a table take fewer arguments than the caller passes.
        const code = isFunction(value) ? this.func(value, scope, pre, { variadic: true }) : ex(value);
        return `${quote(key)}: ${code}`;
      });
      return `{${items.join(", ")}}`;
    }
    if (isFunction(node)) return this.func(node, scope, pre, { variadic: true });
    if (ts.isPropertyAccessExpression(node)) {
      const prop = node.name.text;
      if (isGlobal(node.expression, "Math") && prop === "PI") return "js.PI";
      const optional = node.flags & ts.NodeFlags.OptionalChain;
      if (prop === "length" && !optional) return `js.length(${ex(node.expression)})`;
      if (isBuiltinMember(node.name) && prop !== "length") this.fail(node, "built-in property");
      return `js.${optional ? "get_optional" : "get"}(${ex(node.expression)}, ${quote(prop)})`;
    }
    if (ts.isElementAccessExpression(node)) {
      const optional = node.flags & ts.NodeFlags.OptionalChain;
      return `js.${optional ? "get_optional" : "get"}(${ex(node.expression)}, ${ex(node.argumentExpression)})`;
    }
    if (ts.isConditionalExpression(node)) {
      const test = this.cond(node.condition, scope, pre);
      return `(${ex(node.whenTrue)} if ${test} else ${ex(node.whenFalse)})`;
    }
    if (ts.isTypeOfExpression(node)) return `js.type_of(${ex(node.expression)})`;
    if (ts.isPrefixUnaryExpression(node)) {
      if (node.operator === K.ExclamationToken) return `(not ${this.cond(node.operand, scope, pre)})`;
      if (node.operator === K.MinusToken) {
        const operand = unwrap(node.operand);
        return ts.isNumericLiteral(operand) ? `-${Number(operand.text)}` : `js.neg(${ex(operand)})`;
      }
      this.fail(node, "unary operator");
    }
    if (ts.isBinaryExpression(node)) return this.binary(node, scope, pre);
    if (ts.isCallExpression(node)) return this.call(node, scope, pre);
    if (ts.isNewExpression(node)) {
      const args = node.arguments ?? [];
      if (isGlobal(node.expression, "Date") && args.length === 1) return `js.Date(${ex(args[0])})`;
      if (isGlobal(node.expression, "Map") && args.length <= 1) return `js.Map(${args.map(ex).join("")})`;
      this.fail(node, "constructor");
    }
    return this.fail(node, `expression ${K[node.kind]}`);
  }

  binary(node, scope, pre) {
    const { left, right } = node;
    const op = node.operatorToken.kind;
    const ex = (child) => this.expr(child, scope, pre);
    if (COMPARE.has(op)) return `js.${COMPARE.get(op)}(${ex(left)}, ${ex(right)})`;
    if (ARITHMETIC.has(op)) return `js.${ARITHMETIC.get(op)}(${ex(left)}, ${ex(right)})`;
    if (op === K.InKeyword) {
      const of = unwrap(right);
      const prototype =
        ts.isPropertyAccessExpression(of) && isGlobal(of.expression, "Object") && of.name.text === "prototype";
      if (!prototype) this.fail(node, "`in` of anything but Object.prototype");
      return `js.in_object_prototype(${ex(left)})`;
    }
    if (op === K.EqualsEqualsEqualsToken || op === K.ExclamationEqualsEqualsToken) {
      const equal = op === K.EqualsEqualsEqualsToken;
      const r = unwrap(right);
      const l = unwrap(left);
      if (ts.isIdentifier(r) && r.text === "undefined") return `(${ex(left)} is ${equal ? "" : "not "}js.UNDEF)`;
      if (r.kind === K.NullKeyword) return `(${ex(left)} is ${equal ? "" : "not "}None)`;
      if (ts.isStringLiteralLike(r) || ts.isStringLiteralLike(l)) {
        return `(${ex(left)} ${equal ? "==" : "!="} ${ex(right)})`;
      }
      return `${equal ? "" : "not "}js.same(${ex(left)}, ${ex(right)})`;
    }
    if (op === K.PlusToken) {
      if (this.isString(left) || this.isString(right)) {
        return `(${this.asString(left, scope, pre)} + ${this.asString(right, scope, pre)})`;
      }
      return `js.add(${ex(left)}, ${ex(right)})`;
    }
    if (op === K.BarBarToken || op === K.AmpersandAmpersandToken || op === K.QuestionQuestionToken) {
      if (op !== K.QuestionQuestionToken && this.isBoolean(node)) return this.cond(node, scope, pre);
      const a = ex(left);
      if (op !== K.AmpersandAmpersandToken && this.isPlain(right)) {
        return `js.${op === K.BarBarToken ? "or_" : "nullish"}(${a}, ${ex(right)})`;
      }
      const temp = this.fresh("v");
      const test = `js.${op === K.QuestionQuestionToken ? "defined" : "truthy"}(${temp} := ${a})`;
      const b = ex(right);
      return op === K.AmpersandAmpersandToken ? `(${b} if ${test} else ${temp})` : `(${temp} if ${test} else ${b})`;
    }
    if (op === K.EqualsToken && ts.isElementAccessExpression(left)) {
      return `js.put(${ex(left.expression)}, ${ex(left.argumentExpression)}, ${ex(right)})`;
    }
    return this.fail(node, `operator ${node.operatorToken.getText()}`);
  }

  call(node, scope, pre) {
    const callee = unwrap(node.expression);
    const args = node.arguments;
    const ex = (child) => this.expr(child, scope, pre);
    if (node.questionDotToken) this.fail(node, "optional call");
    if (isFunction(callee)) {
      if (args.length || !ts.isBlock(callee.body)) this.fail(node, "immediately invoked function");
      return `${this.func(callee, scope, pre)}()`;
    }
    if (isGlobal(callee, "String")) return `js.s(${ex(args[0])})`;
    if (isGlobal(callee, "Number")) return `js.to_number(${ex(args[0])})`;
    if (isGlobal(callee, "Boolean")) return this.cond(args[0], scope, pre);
    if (ts.isPropertyAccessExpression(callee) && isBuiltinMember(callee.name)) {
      return this.method(node, callee, scope, pre);
    }
    if (isGlobal(callee, "parseInt")) {
      if (args.length !== 2 || args[1].getText() !== "16") this.fail(node, "parseInt in another base");
      return `js.parse_hex(${ex(args[0])})`;
    }
    if (ts.isIdentifier(callee) && isBuiltinMember(callee)) this.fail(node, "global function");
    const list = args.map((a) => (ts.isSpreadElement(a) ? `*js.iterate(${ex(a.expression)})` : ex(a)));
    return `${ex(callee)}(${list.join(", ")})`;
  }

  method(node, callee, scope, pre) {
    const ex = (child) => this.expr(child, scope, pre);
    const target = callee.expression;
    const name = callee.name.text;
    const args = node.arguments;
    const n = args.length;
    if (node.flags & ts.NodeFlags.OptionalChain) this.fail(node, "optional method call");
    if (this.isHasOwnCall(node)) return `js.has_own(${ex(args[0])}, ${ex(args[1])})`;

    if (isGlobal(target, "Array")) {
      if (name === "isArray") return `js.is_array(${ex(args[0])})`;
      if (name === "from" && n === 1) return `js.code_points(${ex(args[0])})`;
      if (name === "from" && n === 2) {
        const source = unwrap(args[0]);
        if (!ts.isObjectLiteralExpression(source)) this.fail(node, "Array.from");
        const fn = this.callback(args[1], scope, pre, 2);
        if (fn.arity !== 2) this.fail(node, "Array.from callback");
        return `js.array_from(${ex(source.properties[0].initializer)}, ${fn.code})`;
      }
    } else if (isGlobal(target, "Math")) {
      if (Object.hasOwn(MATH, name) && n >= MATH[name][1] && n <= MATH[name][2]) {
        if (args.some(ts.isSpreadElement)) this.fail(node, "spread into Math");
        return `js.${MATH[name][0]}(${args.map(ex).join(", ")})`;
      }
    } else if (isGlobal(target, "Number")) {
      if (name === "isNaN") return `js.is_nan(${ex(args[0])})`;
    } else if (isGlobal(target, "Object")) {
      if (["keys", "values", "entries"].includes(name)) return `js.${name}(${ex(args[0])})`;
    } else {
      const simple = {
        "join/1": "join",
        "includes/1": "includes",
        "indexOf/1": "index_of",
        "toFixed/1": "to_fixed",
        "slice/1": "slice_",
        "slice/2": "slice_",
        "padStart/2": "pad_start",
        "trim/0": "trim",
        "toLowerCase/0": "lower",
        "toUpperCase/0": "upper",
        "startsWith/1": "starts_with",
        "endsWith/1": "ends_with",
        "charAt/1": "char_at",
        "charCodeAt/1": "char_code_at",
      }[`${name}/${n}`];
      if (simple) return `js.${simple}(${[target, ...args].map(ex).join(", ")})`;
      if (name === "toString" && n === 1 && args[0].getText() === "16") return `js.to_hex(${ex(target)})`;
      if (DATE_METHODS[name] && n === 0) return `${ex(target)}.${DATE_METHODS[name]}()`;
      if (name === "split" && n === 1) {
        const pattern = unwrap(args[0]);
        if (!ts.isRegularExpressionLiteral(pattern) || /(^|[^\\])\((?!\?:)/.test(pattern.text)) {
          this.fail(node, "split without a regex free of groups");
        }
        return `js.split_text(${ex(target)}, ${this.regex(pattern)})`;
      }
      if (name === "push" && n === 1) return `${ex(target)}.append(${ex(args[0])})`;
      if (name === "get" && n === 1) return `${ex(target)}.get(${ex(args[0])})`;
      if (name === "set" && n === 2) return `${ex(target)}.set(${ex(args[0])}, ${ex(args[1])})`;
      if (["map", "filter", "find", "forEach", "some"].includes(name) && n === 1) {
        const array = ex(target);
        const indexed = name === "map" || name === "forEach" || name === "some";
        const fn = this.callback(args[0], scope, pre, indexed ? 2 : 1);
        if (name === "map") return `js.${fn.arity === 2 ? "map_indexed" : "map_"}(${array}, ${fn.code})`;
        if (name === "some") return `js.${fn.arity === 2 ? "some_indexed" : "some"}(${array}, ${fn.code})`;
        if (name === "forEach") {
          if (fn.arity !== 2) this.fail(node, "forEach without an index");
          return `js.for_each_indexed(${array}, ${fn.code})`;
        }
        return `js.${name === "filter" ? "filter_" : "find"}(${array}, ${fn.code})`;
      }
      if (name === "replace" && n === 2) {
        const pattern = unwrap(args[0]);
        if (ts.isStringLiteralLike(pattern)) {
          const by = unwrap(args[1]);
          if (!ts.isStringLiteralLike(by) || by.text.includes("$")) this.fail(node, "text replacement");
          return `js.replace_text(${ex(target)}, ${pyString(pattern.text)}, ${pyString(by.text)})`;
        }
        if (!ts.isRegularExpressionLiteral(pattern)) this.fail(node, "replace without a literal pattern");
        const subject = ex(target);
        const rx = this.regex(pattern);
        const by = unwrap(args[1]);
        if (ts.isStringLiteralLike(by)) {
          if (/\$[`'<]/.test(by.text)) this.fail(node, "replacement pattern");
          const template = by.text
            .replace(/\\/g, "\\\\")
            .replace(/\$(\$|&|\d+)/g, (_, r) => (r === "$" ? "$" : r === "&" ? "\\g<0>" : `\\g<${r}>`));
          return `js.replace(${subject}, ${rx}, ${pyString(template)})`;
        }
        if (!isFunction(by)) this.fail(node, "replacement");
        const fn = this.func(by, scope, pre);
        return `js.replace_with(${subject}, ${rx}, ${fn}, ${by.parameters.length})`;
      }
      if (name === "exec" && n === 1) {
        this.statelessRegex(target);
        return `js.exec_(${ex(target)}, ${ex(args[0])})`;
      }
      if (name === "test" && n === 1) {
        this.statelessRegex(target);
        return `js.test(${ex(target)}, ${ex(args[0])})`;
      }
    }
    return this.fail(node, `method ${name}/${n}`);
  }

  // -- statements ------------------------------------------------------------

  terminates(statements) {
    const last = statements[statements.length - 1];
    if (!last) return false;
    if (ts.isReturnStatement(last)) return true;
    if (ts.isBlock(last)) return this.terminates(last.statements);
    if (ts.isIfStatement(last)) {
      return !!last.elseStatement && this.terminates([last.thenStatement]) && this.terminates([last.elseStatement]);
    }
    if (ts.isSwitchStatement(last)) {
      const clauses = last.caseBlock.clauses;
      return (
        clauses.some(ts.isDefaultClause) &&
        clauses.every((c, i) => (!c.statements.length && i < clauses.length - 1) || this.terminates(c.statements))
      );
    }
    return false;
  }

  block(statements, scope) {
    for (const statement of statements) {
      if (ts.isFunctionDeclaration(statement)) this.declare(statement.name, scope);
    }
    return statements.flatMap((statement) => this.statement(statement, scope));
  }

  suite(node, scope) {
    const lines = this.block(ts.isBlock(node) ? node.statements : [node], scope);
    return indent(lines.length ? lines : ["pass"]);
  }

  assignTarget(ident, scope) {
    const { name, scope: owner } = this.lookup(ident);
    if (owner !== scope) scope.outer.add(name);
    return name;
  }

  statement(node, scope) {
    if (
      ts.isInterfaceDeclaration(node) ||
      ts.isTypeAliasDeclaration(node) ||
      ts.isImportDeclaration(node) ||
      ts.isExportDeclaration(node) ||
      ts.isEmptyStatement(node)
    ) {
      return [];
    }
    const pre = [];
    const ex = (child) => this.expr(child, scope, pre);

    if (ts.isFunctionDeclaration(node)) {
      this.func(node, scope, pre, { name: this.declare(node.name, scope) });
      return pre;
    }
    if (ts.isVariableStatement(node)) {
      const lines = [];
      for (const d of node.declarationList.declarations) {
        const before = [];
        if (!ts.isIdentifier(d.name)) {
          const source = this.expr(d.initializer, scope, before);
          lines.push(...before, ...this.destructure(d.name, source, scope));
        } else if (!d.initializer) {
          lines.push(`${this.declare(d.name, scope)}: Any = js.UNDEF`);
        } else if (isFunction(unwrap(d.initializer))) {
          this.func(unwrap(d.initializer), scope, before, { name: this.declare(d.name, scope) });
          lines.push(...before);
        } else {
          const value = this.expr(d.initializer, scope, before);
          lines.push(...before, `${this.declare(d.name, scope)}: Any = ${value}`);
        }
      }
      return lines;
    }
    if (ts.isExpressionStatement(node)) {
      const e = unwrap(node.expression);
      if (ts.isVoidExpression(e) && this.isPlain(e.expression)) return [];
      if (ts.isBinaryExpression(e) && ts.isIdentifier(e.left)) {
        const op = e.operatorToken.kind;
        if (op === K.EqualsToken) {
          const value = ex(e.right);
          return [...pre, `${this.assignTarget(e.left, scope)} = ${value}`];
        }
        if (op === K.PlusEqualsToken) {
          const name = this.assignTarget(e.left, scope);
          const value = ex(e.right);
          return [...pre, `${name} = js.add(${name}, ${value})`];
        }
        if (op === K.QuestionQuestionEqualsToken) {
          // The right side runs only when the left one is null or undefined.
          const name = this.assignTarget(e.left, scope);
          const value = ex(e.right);
          return [`if not js.defined(${name}):`, ...indent([...pre, `${name} = ${value}`])];
        }
      }
      const code = ex(e);
      return [...pre, code];
    }
    if (ts.isIfStatement(node)) {
      const test = this.cond(node.expression, scope, pre);
      const lines = [...pre, `if ${test}:`, ...this.suite(node.thenStatement, scope)];
      if (node.elseStatement) {
        if (ts.isIfStatement(node.elseStatement)) {
          const rest = this.statement(node.elseStatement, scope);
          if (rest[0].startsWith("if ")) lines.push(`el${rest[0]}`, ...rest.slice(1));
          else lines.push("else:", ...indent(rest));
        } else {
          lines.push("else:", ...this.suite(node.elseStatement, scope));
        }
      }
      return lines;
    }
    if (ts.isReturnStatement(node)) {
      const value = node.expression ? ex(node.expression) : "js.UNDEF";
      return [...pre, `return ${value}`];
    }
    if (ts.isContinueStatement(node) && !node.label) return ["continue"];
    if (ts.isBlock(node)) return this.block(node.statements, scope);
    if (ts.isForOfStatement(node)) {
      const source = ex(node.expression);
      const binding = node.initializer.declarations[0].name;
      if (ts.isIdentifier(binding)) {
        const target = this.declare(binding, scope);
        return [...pre, `for ${target} in js.iterate(${source}):`, ...this.suite(node.statement, scope)];
      }
      const item = this.fresh("item");
      const unpacked = this.destructure(binding, item, scope);
      return [
        ...pre,
        `for ${item} in js.iterate(${source}):`,
        ...indent(unpacked),
        ...this.suite(node.statement, scope),
      ];
    }
    if (ts.isForStatement(node)) return this.countedLoop(node, scope);
    if (ts.isSwitchStatement(node)) return this.switchStatement(node, scope);
    return this.fail(node, `statement ${K[node.kind]}`);
  }

  /** `for (let i = a; i < b; i += c)` or `(i = a; i > b; i--)`, with `b` fixed, as a range. */
  countedLoop(node, scope) {
    const { initializer: init, condition, incrementor: step } = node;
    const decl = init && ts.isVariableDeclarationList(init) && init.declarations.length === 1 ? init.declarations[0] : null;
    if (!decl || !condition || !step || !ts.isBinaryExpression(condition)) this.fail(node, "loop");
    const op = condition.operatorToken.kind;
    if (condition.left.getText() !== decl.name.getText()) this.fail(node, "loop condition");
    const down = op === K.GreaterThanToken || op === K.GreaterThanEqualsToken;
    if (!down && op !== K.LessThanToken && op !== K.LessThanEqualsToken) this.fail(node, "loop condition");
    const pre = [];
    const from = this.expr(decl.initializer, scope, pre);
    let to = this.expr(condition.right, scope, pre);
    if (op === K.LessThanEqualsToken) to += " + 1";
    if (op === K.GreaterThanEqualsToken) to += " - 1";
    let by = null;
    if (down) {
      if (!ts.isPostfixUnaryExpression(step) || step.operator !== K.MinusMinusToken) this.fail(node, "loop step");
      by = "-1";
    } else if (ts.isPostfixUnaryExpression(step) && step.operator === K.PlusPlusToken) by = "1";
    else if (ts.isBinaryExpression(step) && step.operatorToken.kind === K.PlusEqualsToken) {
      by = this.expr(step.right, scope, pre);
    } else this.fail(node, "loop step");
    const bound = condition.right.getText();
    const visit = (n) => {
      if (ts.isBinaryExpression(n)) {
        const assigns = n.operatorToken.kind >= K.FirstAssignment && n.operatorToken.kind <= K.LastAssignment;
        if (assigns && [bound, decl.name.getText()].includes(n.left.getText())) {
          this.fail(n, "loop bound changed inside the loop");
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(node.statement);
    const name = this.declare(decl.name, scope);
    const range = by === "1" ? `${from}, ${to}` : `${from}, ${to}, ${by}`;
    return [...pre, `for ${name} in range(${range}):`, ...this.suite(node.statement, scope)];
  }

  switchStatement(node, scope) {
    const pre = [];
    const subject = this.fresh("case");
    const lines = [`${subject}: Any = ${this.expr(node.expression, scope, pre)}`];
    const clauses = node.caseBlock.clauses;
    let tests = [];
    let branches = 0;
    clauses.forEach((clause, i) => {
      const last = i === clauses.length - 1;
      const isDefault = ts.isDefaultClause(clause);
      if (isDefault && !last) this.fail(clause, "default is not the last case");
      if (!isDefault) {
        const label = unwrap(clause.expression);
        if (!ts.isStringLiteralLike(label) && !ts.isNumericLiteral(label)) this.fail(clause, "case label");
        const value = this.expr(label, scope, pre);
        tests.push(ts.isStringLiteralLike(label) ? `${subject} == ${value}` : `js.same(${subject}, ${value})`);
        if (!clause.statements.length && !last) return;
      }
      if (!last && !this.terminates(clause.statements)) this.fail(clause, "case falls through");
      const body = this.block(clause.statements, scope);
      const suite = indent(body.length ? body : ["pass"]);
      if (isDefault) {
        if (branches) lines.push("else:", ...suite);
        else lines.push(...body);
      } else {
        lines.push(`${branches ? "elif" : "if"} ${tests.join(" or ")}:`, ...suite);
      }
      branches += 1;
      tests = [];
    });
    return [...pre, ...lines];
  }

  // -- module ----------------------------------------------------------------

  emit() {
    const statements = this.file.statements;
    for (const statement of statements) {
      if (!ts.isImportDeclaration(statement) || statement.importClause?.isTypeOnly) continue;
      const named = statement.importClause?.namedBindings;
      if (!named || !ts.isNamedImports(named)) this.fail(statement, "import");
      const from = moduleName(statement.moduleSpecifier.text.replace(/\.js$/, ".ts"));
      for (const element of named.elements) {
        if (element.isTypeOnly) continue;
        const original = safeName((element.propertyName ?? element.name).text);
        this.imports.set(this.declare(element.name, this.root), { from, original });
      }
    }
    for (const statement of statements) {
      if (ts.isFunctionDeclaration(statement)) this.declare(statement.name, this.root);
      if (ts.isVariableStatement(statement)) {
        for (const d of statement.declarationList.declarations) this.declare(d.name, this.root);
      }
    }
    const body = [];
    for (const statement of statements) {
      const lines = this.statement(statement, this.root);
      if (lines.length) body.push(...lines, "", "");
    }
    const imports = new Map();
    for (const [local, { from, original }] of this.imports) {
      if (!this.used.has(local)) continue;
      const item = local === original ? local : `${original} as ${local}`;
      imports.set(from, [...(imports.get(from) ?? []), item]);
    }
    const relative = this.file.fileName.slice(this.file.fileName.indexOf("src/pdf/"));
    const sha = createHash("sha256").update(readFileSync(this.file.fileName)).digest("hex");
    return [
      "# GENERATED by scripts/generate_pdf.mjs from the Node SDK's templates. Do not edit by hand.",
      `# Source: lifeastroapi-node/${relative}`,
      `# Source sha256: ${sha}`,
      "# Run `node scripts/generate_pdf.mjs` to regenerate.",
      "from __future__ import annotations",
      "",
      "from typing import Any",
      "",
      "from .. import _js as js",
      ...[...imports].sort().map(([from, items]) => `from .${from} import ${items.sort().join(", ")}`),
      "",
      ...[...this.regexes.values()].map(({ name, args }) => `${name} = js.Regex(${args})`),
      "",
      ...body,
    ]
      .join("\n")
      .replace(/\n*$/, "\n");
  }
}

mkdirSync(OUT, { recursive: true });
// Translate everything first, so a failure leaves the previous output untouched.
const modules = SOURCES.map((file) => new Module(program.getSourceFile(file)));
const written = modules.map((module, i) => [join(OUT, `${moduleName(SOURCES[i])}.py`), module.emit()]);
const runStarts = modules.reduce((n, module) => n + (module.runStarts ?? 0), 0);
if (runStarts !== RUN_START.size) {
  throw new Error(`${runStarts} of the ${RUN_START.size} RUN_START patterns found: shared.ts changed, review them`);
}
written.push([
  join(OUT, "__init__.py"),
  '"""The report templates, generated by ``scripts/generate_pdf.mjs``. Imported on first use."""\n',
]);
for (const [path, text] of written) writeFileSync(path, text);

const ruff =
  process.env.RUFF ??
  [join(ROOT, ".venv", "bin", "ruff"), join(ROOT, ".venv", "Scripts", "ruff.exe")].find(existsSync) ??
  "ruff";
for (const args of [
  ["check", "--quiet", "--fix", "--exit-zero", "--select", "I,F541", OUT],
  ["format", "--quiet", OUT],
]) {
  const run = spawnSync(ruff, args, { cwd: ROOT, stdio: "inherit" });
  if (run.status !== 0) throw new Error(`ruff ${args[0]} failed (set RUFF to its path)`);
}
console.log(`${written.length} files written to ${OUT}`);
