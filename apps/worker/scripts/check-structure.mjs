#!/usr/bin/env node
/**
 * Enforce the Worker TypeScript structural floor with expiring debt ratchets.
 *
 * The pinned TypeScript compiler supplies the syntax tree. Only
 * TypeScript and TSX files below `apps/worker/src/` are scanned. Existing violations must be
 * recorded exactly, while clean code may not cross any limit.
 */

import fs from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROOT = path.resolve(SCRIPT_DIR, "../../..");
const DEFAULT_CONFIG = "docs/refactoring/worker-structural-debt.json";
const SOURCE_ROOT = "apps/worker/src";
const CONFIG_VERSION = 1;
const MINIMUM_SOURCE_FILES = 100;

export const LIMITS = Object.freeze({
  max_file_lines: 400,
  max_function_lines: 80,
  max_parameters: 5,
  max_complexity: 15,
  max_nesting_depth: 4,
});

const CONFIG_FIELDS = new Set(["version", "limits", "exemptions"]);
const LIMIT_FIELDS = new Set(Object.keys(LIMITS));
const EXEMPTION_FIELDS = new Set([
  "file_lines",
  "max_function_lines",
  "max_parameters",
  "max_complexity",
  "max_nesting_depth",
  "over_limit_functions",
  "owner",
  "reason",
  "expires",
]);
const FUNCTION_FIELDS = new Set([
  "name",
  "line",
  "column",
  "lines",
  "parameters",
  "complexity",
  "nesting_depth",
]);

export class StructureError extends Error {}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertExactFields(value, expected, label) {
  if (!isObject(value)) throw new StructureError(`${label} must be an object`);
  const actual = new Set(Object.keys(value));
  const missing = [...expected].filter((key) => !actual.has(key)).sort();
  const extra = [...actual].filter((key) => !expected.has(key)).sort();
  if (missing.length || extra.length) {
    throw new StructureError(
      `${label} fields malformed (missing=${JSON.stringify(missing)}, extra=${JSON.stringify(extra)})`,
    );
  }
}

/** Parse JSON while rejecting duplicate object keys instead of resolving last-wins. */
export function parseJsonStrict(text) {
  let cursor = 0;

  const fail = (message) => {
    throw new StructureError(`invalid JSON at offset ${cursor}: ${message}`);
  };
  const skipSpace = () => {
    while (cursor < text.length && /\s/u.test(text[cursor])) cursor += 1;
  };
  const parseString = () => {
    if (text[cursor] !== '"') fail("expected string");
    const start = cursor;
    cursor += 1;
    while (cursor < text.length) {
      const character = text[cursor];
      if (character === '"') {
        cursor += 1;
        try {
          return JSON.parse(text.slice(start, cursor));
        } catch (error) {
          fail(error instanceof Error ? error.message : "invalid string");
        }
      }
      if (character === "\\") {
        cursor += 2;
        continue;
      }
      if (character.charCodeAt(0) < 0x20) fail("control character in string");
      cursor += 1;
    }
    fail("unterminated string");
  };
  const parseNumber = () => {
    const match = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/uy.exec(text.slice(cursor));
    if (!match) fail("invalid number");
    cursor += match[0].length;
    return Number(match[0]);
  };
  const parseValue = () => {
    skipSpace();
    if (text[cursor] === '"') return parseString();
    if (text[cursor] === "{") return parseObject();
    if (text[cursor] === "[") return parseArray();
    for (const [token, value] of [["true", true], ["false", false], ["null", null]]) {
      if (text.startsWith(token, cursor)) {
        cursor += token.length;
        return value;
      }
    }
    return parseNumber();
  };
  const parseArray = () => {
    const result = [];
    cursor += 1;
    skipSpace();
    if (text[cursor] === "]") {
      cursor += 1;
      return result;
    }
    while (cursor < text.length) {
      result.push(parseValue());
      skipSpace();
      if (text[cursor] === "]") {
        cursor += 1;
        return result;
      }
      if (text[cursor] !== ",") fail("expected ',' or ']' in array");
      cursor += 1;
    }
    fail("unterminated array");
  };
  const parseObject = () => {
    const result = Object.create(null);
    const seen = new Set();
    cursor += 1;
    skipSpace();
    if (text[cursor] === "}") {
      cursor += 1;
      return result;
    }
    while (cursor < text.length) {
      skipSpace();
      const key = parseString();
      if (seen.has(key)) throw new StructureError(`duplicate JSON key: ${JSON.stringify(key)}`);
      seen.add(key);
      skipSpace();
      if (text[cursor] !== ":") fail("expected ':' after object key");
      cursor += 1;
      result[key] = parseValue();
      skipSpace();
      if (text[cursor] === "}") {
        cursor += 1;
        return result;
      }
      if (text[cursor] !== ",") fail("expected ',' or '}' in object");
      cursor += 1;
    }
    fail("unterminated object");
  };

  const value = parseValue();
  skipSpace();
  if (cursor !== text.length) fail("trailing input");
  return value;
}

function isFunctionNode(node) {
  return (
    ts.isFunctionDeclaration(node) ||
    ts.isFunctionExpression(node) ||
    ts.isArrowFunction(node) ||
    ts.isMethodDeclaration(node) ||
    ts.isGetAccessorDeclaration(node) ||
    ts.isSetAccessorDeclaration(node) ||
    ts.isConstructorDeclaration(node)
  );
}

function nodeName(node, sourceFile) {
  if (node.name) return node.name.getText(sourceFile);
  const parent = node.parent;
  if (ts.isVariableDeclaration(parent)) return parent.name.getText(sourceFile);
  if (ts.isPropertyAssignment(parent)) return parent.name.getText(sourceFile);
  if (ts.isPropertyDeclaration(parent) && parent.name) return parent.name.getText(sourceFile);
  if (ts.isJsxAttribute(parent)) return parent.name.getText(sourceFile);
  if (ts.isCallExpression(parent)) {
    const index = parent.arguments.findIndex((argument) => argument === node);
    return `${parent.expression.getText(sourceFile)}[${index}]`;
  }
  return "<anonymous>";
}

function isComplexityNode(node) {
  return (
    ts.isIfStatement(node) ||
    ts.isForStatement(node) ||
    ts.isForInStatement(node) ||
    ts.isForOfStatement(node) ||
    ts.isWhileStatement(node) ||
    ts.isDoStatement(node) ||
    ts.isCatchClause(node) ||
    ts.isConditionalExpression(node) ||
    ts.isCaseClause(node)
  );
}

function complexityOf(root) {
  let complexity = 1;
  const visit = (node) => {
    if (node !== root && isFunctionNode(node)) return;
    if (isComplexityNode(node)) complexity += 1;
    if (
      ts.isBinaryExpression(node) &&
      [
        ts.SyntaxKind.AmpersandAmpersandToken,
        ts.SyntaxKind.BarBarToken,
        ts.SyntaxKind.QuestionQuestionToken,
        ts.SyntaxKind.AmpersandAmpersandEqualsToken,
        ts.SyntaxKind.BarBarEqualsToken,
        ts.SyntaxKind.QuestionQuestionEqualsToken,
      ].includes(node.operatorToken.kind)
    ) {
      complexity += 1;
    }
    ts.forEachChild(node, visit);
  };
  if (root.body) visit(root.body);
  return complexity;
}

function nestingDepthOf(root) {
  let maximum = 0;
  const visitChildren = (node, depth) => ts.forEachChild(node, (child) => visit(child, depth));
  const visit = (node, depth) => {
    if (node !== root && isFunctionNode(node)) return;
    if (ts.isIfStatement(node)) {
      const nested = depth + 1;
      maximum = Math.max(maximum, nested);
      visit(node.expression, depth);
      visit(node.thenStatement, nested);
      if (node.elseStatement) {
        // An else-if chain is one choice at the same structural depth.
        visit(node.elseStatement, ts.isIfStatement(node.elseStatement) ? depth : nested);
      }
      return;
    }
    if (
      ts.isForStatement(node) ||
      ts.isForInStatement(node) ||
      ts.isForOfStatement(node) ||
      ts.isWhileStatement(node) ||
      ts.isDoStatement(node)
    ) {
      const nested = depth + 1;
      maximum = Math.max(maximum, nested);
      ts.forEachChild(node, (child) => visit(child, child === node.statement ? nested : depth));
      return;
    }
    if (ts.isSwitchStatement(node)) {
      const nested = depth + 1;
      maximum = Math.max(maximum, nested);
      visit(node.expression, depth);
      visit(node.caseBlock, nested);
      return;
    }
    if (ts.isTryStatement(node)) {
      const nested = depth + 1;
      maximum = Math.max(maximum, nested);
      visit(node.tryBlock, nested);
      if (node.catchClause) visit(node.catchClause, nested);
      if (node.finallyBlock) visit(node.finallyBlock, nested);
      return;
    }
    if (ts.isConditionalExpression(node)) {
      const nested = depth + 1;
      maximum = Math.max(maximum, nested);
      visit(node.condition, depth);
      visit(node.whenTrue, nested);
      visit(node.whenFalse, nested);
      return;
    }
    visitChildren(node, depth);
  };
  if (root.body) visit(root.body, 0);
  return maximum;
}

function functionMetric(node, sourceFile, scope) {
  const start = node.getStart(sourceFile, false);
  const end = Math.max(start, node.getEnd() - 1);
  const startLocation = sourceFile.getLineAndCharacterOfPosition(start);
  const endLocation = sourceFile.getLineAndCharacterOfPosition(end);
  const simpleName = nodeName(node, sourceFile);
  return {
    name: [...scope, simpleName].join("."),
    line: startLocation.line + 1,
    column: startLocation.character + 1,
    lines: endLocation.line - startLocation.line + 1,
    parameters: node.parameters.length,
    complexity: complexityOf(node),
    nesting_depth: nestingDepthOf(node),
  };
}

function physicalLines(source) {
  if (!source.length) return 0;
  const lines = source.split(/\r\n|\r|\n/u).length;
  return /(?:\r\n|\r|\n)$/u.test(source) ? lines - 1 : lines;
}

function functionSort(left, right) {
  return left.line - right.line || left.column - right.column || left.name.localeCompare(right.name);
}

export function scanSourceFile(filePath, relativePath) {
  let source;
  try {
    source = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    throw new StructureError(`cannot read ${relativePath}: ${error.message}`);
  }
  const scriptKind = filePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const sourceFile = ts.createSourceFile(filePath, source, ts.ScriptTarget.Latest, true, scriptKind);
  if (sourceFile.parseDiagnostics.length) {
    const diagnostic = sourceFile.parseDiagnostics[0];
    const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, " ");
    throw new StructureError(`cannot parse ${relativePath}: ${message}`);
  }
  const functions = [];
  const visit = (node, scope) => {
    let childScope = scope;
    if ((ts.isClassDeclaration(node) || ts.isClassExpression(node)) && node.name) {
      childScope = [...scope, node.name.getText(sourceFile)];
    }
    if (isFunctionNode(node) && node.body) {
      const metric = functionMetric(node, sourceFile, childScope);
      functions.push(metric);
      childScope = [...childScope, nodeName(node, sourceFile)];
    }
    ts.forEachChild(node, (child) => visit(child, childScope));
  };
  visit(sourceFile, []);
  functions.sort(functionSort);
  return {
    path: relativePath,
    file_lines: physicalLines(source),
    functions,
    max_function_lines: Math.max(0, ...functions.map((item) => item.lines)),
    max_parameters: Math.max(0, ...functions.map((item) => item.parameters)),
    max_complexity: Math.max(0, ...functions.map((item) => item.complexity)),
    max_nesting_depth: Math.max(0, ...functions.map((item) => item.nesting_depth)),
  };
}

function sourcePaths(directory) {
  const result = [];
  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const child = path.join(current, entry.name);
      if (entry.isSymbolicLink()) throw new StructureError(`source symlink is out of scope: ${child}`);
      if (entry.isDirectory()) walk(child);
      if (entry.isFile() && /\.(?:ts|tsx)$/u.test(entry.name)) result.push(child);
    }
  };
  walk(directory);
  return result;
}

export function scanTree(repoRoot, minimumFiles = MINIMUM_SOURCE_FILES) {
  const sourceRoot = path.join(repoRoot, SOURCE_ROOT);
  if (!fs.existsSync(sourceRoot) || !fs.statSync(sourceRoot).isDirectory()) {
    throw new StructureError(`missing Worker source root: ${sourceRoot}`);
  }
  const paths = sourcePaths(sourceRoot);
  if (paths.length < minimumFiles) {
    throw new StructureError(
      `Worker source scan found ${paths.length} files; expected at least ${minimumFiles}`,
    );
  }
  return paths.map((filePath) => scanSourceFile(filePath, path.relative(repoRoot, filePath).split(path.sep).join("/")));
}

function isPositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

function isIsoDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/u.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

function currentLocalDate() {
  const now = new Date();
  const year = String(now.getFullYear()).padStart(4, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isFunctionViolation(metric) {
  return (
    metric.lines > LIMITS.max_function_lines ||
    metric.parameters > LIMITS.max_parameters ||
    metric.complexity > LIMITS.max_complexity ||
    metric.nesting_depth > LIMITS.max_nesting_depth
  );
}

function overLimitFunctions(metric) {
  return metric.functions.filter(isFunctionViolation);
}

function isFileViolation(metric) {
  return metric.file_lines > LIMITS.max_file_lines || overLimitFunctions(metric).length > 0;
}

function validateFunctionRecord(filePath, value, index) {
  const label = `exemption ${filePath} function baseline ${index}`;
  assertExactFields(value, FUNCTION_FIELDS, label);
  if (typeof value.name !== "string" || !value.name.trim() || value.name !== value.name.trim()) {
    throw new StructureError(`${label} has invalid name`);
  }
  if (!isPositiveInteger(value.line) || !isPositiveInteger(value.column) || !isPositiveInteger(value.lines)) {
    throw new StructureError(`${label} has invalid source span`);
  }
  if (
    !isNonNegativeInteger(value.parameters) ||
    !isPositiveInteger(value.complexity) ||
    !isNonNegativeInteger(value.nesting_depth)
  ) {
    throw new StructureError(`${label} has invalid parameters, complexity, or nesting depth`);
  }
  if (!isFunctionViolation(value)) throw new StructureError(`${label} is not over any function limit`);
  return value;
}

function validatePath(filePath) {
  const normal = path.posix.normalize(filePath);
  if (
    !filePath ||
    filePath.includes("\\") ||
    path.posix.isAbsolute(filePath) ||
    normal !== filePath ||
    !filePath.startsWith(`${SOURCE_ROOT}/`) ||
    !/\.(?:ts|tsx)$/u.test(filePath)
  ) {
    throw new StructureError(`invalid Worker exemption path: ${JSON.stringify(filePath)}`);
  }
}

function validateExemption(filePath, value, today) {
  validatePath(filePath);
  assertExactFields(value, EXEMPTION_FIELDS, `exemption ${filePath}`);
  if (!isPositiveInteger(value.file_lines)) throw new StructureError(`exemption ${filePath} has invalid file_lines`);
  for (const field of ["max_function_lines", "max_parameters", "max_complexity", "max_nesting_depth"]) {
    if (!isNonNegativeInteger(value[field])) throw new StructureError(`exemption ${filePath} has invalid ${field}`);
  }
  if (!Array.isArray(value.over_limit_functions)) {
    throw new StructureError(`exemption ${filePath} over_limit_functions must be a list`);
  }
  const functions = value.over_limit_functions.map((item, index) => validateFunctionRecord(filePath, item, index));
  const identities = new Set();
  const names = new Set();
  for (const item of functions) {
    const identity = functionIdentity(item);
    if (identities.has(identity)) throw new StructureError(`exemption ${filePath} repeats function baseline ${identity}`);
    if (names.has(item.name)) {
      throw new StructureError(`exemption ${filePath} repeats function name ${item.name}; provenance would be ambiguous`);
    }
    identities.add(identity);
    names.add(item.name);
  }
  const sorted = [...functions].sort(functionSort);
  if (functions.some((item, index) => item !== sorted[index])) {
    throw new StructureError(`exemption ${filePath} function baselines must be source ordered`);
  }
  for (const field of ["owner", "reason"]) {
    if (typeof value[field] !== "string" || !value[field].trim() || value[field] !== value[field].trim()) {
      throw new StructureError(`exemption ${filePath} must have a non-empty, trimmed ${field}`);
    }
  }
  if (!isIsoDate(value.expires)) throw new StructureError(`exemption ${filePath} expires must be an ISO date`);
  if (value.expires < today) throw new StructureError(`exemption ${filePath} expired on ${value.expires}`);
  return { ...value, over_limit_functions: functions };
}

function parseConfigDocument(text, today, label) {
  const document = parseJsonStrict(text);
  assertExactFields(document, CONFIG_FIELDS, label);
  if (document.version !== CONFIG_VERSION) {
    throw new StructureError(`unsupported Worker debt catalogue version: ${JSON.stringify(document.version)}`);
  }
  assertExactFields(document.limits, LIMIT_FIELDS, "Worker structural limits");
  for (const [field, expected] of Object.entries(LIMITS)) {
    if (document.limits[field] !== expected) {
      throw new StructureError(`Worker structural limit ${field} must remain ${expected}`);
    }
  }
  if (!isObject(document.exemptions)) throw new StructureError("Worker exemptions must be an object keyed by path");
  return Object.fromEntries(
    Object.entries(document.exemptions).map(([filePath, value]) => [filePath, validateExemption(filePath, value, today)]),
  );
}

export function loadConfig(configPath, today = currentLocalDate()) {
  try {
    return parseConfigDocument(
      fs.readFileSync(configPath, "utf8"),
      today,
      `Worker debt catalogue ${configPath}`,
    );
  } catch (error) {
    if (error instanceof StructureError) throw error;
    throw new StructureError(`cannot load Worker debt catalogue ${configPath}: ${error.message}`);
  }
}

function functionIdentity(metric) {
  return `${metric.name}:${metric.line}:${metric.column}`;
}

function compareExact(label, location, measured, baseline) {
  if (measured > baseline) return [`${label} growth: ${location} is ${measured}; ratchet is ${baseline}`];
  if (measured < baseline) return [`${label} baseline is stale-high: ${location} is ${measured}; lower the ratchet from ${baseline} in this change`];
  return [];
}

function evaluateExemption(metric, exemption) {
  if (!isFileViolation(metric)) return [`stale exemption for clean file: ${metric.path}`];
  const errors = [];
  errors.push(...compareExact("file", metric.path, metric.file_lines, exemption.file_lines));
  errors.push(...compareExact("largest-function", metric.path, metric.max_function_lines, exemption.max_function_lines));
  errors.push(...compareExact("largest-parameter-count", metric.path, metric.max_parameters, exemption.max_parameters));
  errors.push(...compareExact("largest-complexity", metric.path, metric.max_complexity, exemption.max_complexity));
  errors.push(...compareExact("largest-nesting-depth", metric.path, metric.max_nesting_depth, exemption.max_nesting_depth));

  const current = new Map(overLimitFunctions(metric).map((item) => [functionIdentity(item), item]));
  const recorded = new Map(exemption.over_limit_functions.map((item) => [functionIdentity(item), item]));
  for (const identity of [...current.keys()].filter((key) => !recorded.has(key)).sort()) {
    const item = current.get(identity);
    errors.push(
      `new over-limit function: ${metric.path}:${identity} ` +
      `span=${item.lines}/${LIMITS.max_function_lines}, parameters=${item.parameters}/${LIMITS.max_parameters}, ` +
      `complexity=${item.complexity}/${LIMITS.max_complexity}, ` +
      `nesting=${item.nesting_depth}/${LIMITS.max_nesting_depth}`,
    );
  }
  for (const identity of [...recorded.keys()].filter((key) => !current.has(key)).sort()) {
    errors.push(`stale function baseline: ${metric.path}:${identity}; remove or update it in this change`);
  }
  for (const identity of [...current.keys()].filter((key) => recorded.has(key)).sort()) {
    const item = current.get(identity);
    const baseline = recorded.get(identity);
    for (const field of ["lines", "parameters", "complexity", "nesting_depth"]) {
      errors.push(...compareExact(`function-${field}`, `${metric.path}:${identity}`, item[field], baseline[field]));
    }
  }
  return errors;
}

export function evaluate(metrics, exemptions) {
  const errors = [];
  const byPath = new Map(metrics.map((item) => [item.path, item]));
  for (const filePath of Object.keys(exemptions).filter((item) => !byPath.has(item)).sort()) {
    errors.push(`exemption points to a missing or out-of-scope file: ${filePath}`);
  }
  for (const metric of metrics) {
    const exemption = exemptions[metric.path];
    if (exemption) errors.push(...evaluateExemption(metric, exemption));
    else if (isFileViolation(metric)) {
      errors.push(
        `new structural violation: ${metric.path} file=${metric.file_lines}/${LIMITS.max_file_lines}, ` +
        `largest_function=${metric.max_function_lines}/${LIMITS.max_function_lines}, ` +
        `parameters=${metric.max_parameters}/${LIMITS.max_parameters}, ` +
        `complexity=${metric.max_complexity}/${LIMITS.max_complexity}, ` +
        `nesting=${metric.max_nesting_depth}/${LIMITS.max_nesting_depth}`,
      );
    }
  }
  return errors;
}

function growthOnly(label, location, measured, baseline) {
  return measured > baseline
    ? [`trusted baseline ${label} growth: ${location} is ${measured}; prior ratchet is ${baseline}`]
    : [];
}

/**
 * Compare the current exact catalogue with the independently loaded catalogue
 * from the trusted Git base. Source locations may move, but no debt metric or
 * named over-limit function may be added or increased.
 */
export function evaluateTrustedBaseline(current, baseline) {
  const errors = [];
  for (const [filePath, exemption] of Object.entries(current)) {
    const prior = baseline[filePath];
    if (!prior) {
      errors.push(`trusted baseline new debt file: ${filePath}`);
      continue;
    }
    for (const field of [
      "file_lines",
      "max_function_lines",
      "max_parameters",
      "max_complexity",
      "max_nesting_depth",
    ]) {
      errors.push(...growthOnly(field, filePath, exemption[field], prior[field]));
    }
    const priorFunctions = new Map(prior.over_limit_functions.map((item) => [item.name, item]));
    for (const item of exemption.over_limit_functions) {
      const priorItem = priorFunctions.get(item.name);
      if (!priorItem) {
        errors.push(`trusted baseline new over-limit function: ${filePath}:${item.name}`);
        continue;
      }
      for (const field of ["lines", "parameters", "complexity", "nesting_depth"]) {
        errors.push(
          ...growthOnly(
            `function-${field}`,
            `${filePath}:${item.name}`,
            item[field],
            priorItem[field],
          ),
        );
      }
    }
  }
  return errors;
}

function gitOutput(repoRoot, args, failure) {
  try {
    return execFileSync("git", args, {
      cwd: repoRoot,
      encoding: "utf8",
      stdio: ["ignore", "pipe", "pipe"],
    }).trim();
  } catch (error) {
    const detail = error instanceof Error && "stderr" in error
      ? String(error.stderr).trim()
      : "";
    throw new StructureError(`${failure}${detail ? `: ${detail}` : ""}`);
  }
}

function resolveCommit(repoRoot, revision) {
  if (typeof revision !== "string" || !revision.trim() || revision !== revision.trim()) {
    throw new StructureError("trusted baseline ref must be a non-empty, trimmed Git revision");
  }
  if (/[\0\r\n]/u.test(revision)) throw new StructureError("trusted baseline ref contains control characters");
  const commit = gitOutput(
    repoRoot,
    ["rev-parse", "--verify", "--end-of-options", `${revision}^{commit}`],
    `cannot resolve trusted baseline ref ${JSON.stringify(revision)}`,
  );
  if (!/^[0-9a-f]{40}$/u.test(commit)) {
    throw new StructureError(`trusted baseline did not resolve to one full commit: ${JSON.stringify(commit)}`);
  }
  return commit;
}

function gitObjectExists(repoRoot, object) {
  try {
    execFileSync("git", ["cat-file", "-e", object], {
      cwd: repoRoot,
      stdio: "ignore",
    });
    return true;
  } catch {
    return false;
  }
}

function gitSucceeds(repoRoot, args) {
  try {
    execFileSync("git", args, { cwd: repoRoot, stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

export function resolveTrustedBaselineRef(repoRoot, requested = process.env.WORKER_STRUCTURE_BASE_REF) {
  if (requested) return resolveCommit(repoRoot, requested);
  const head = resolveCommit(repoRoot, "HEAD");
  if (!gitObjectExists(repoRoot, "refs/remotes/origin/main^{commit}")) return head;
  const originMain = resolveCommit(repoRoot, "refs/remotes/origin/main");
  const mergeBase = gitOutput(
    repoRoot,
    ["merge-base", head, originMain],
    "cannot resolve the trusted Worker structural merge base",
  );
  if (!/^[0-9a-f]{40}$/u.test(mergeBase)) {
    throw new StructureError(`trusted Worker structural merge base is invalid: ${JSON.stringify(mergeBase)}`);
  }
  return mergeBase;
}

function repositoryPath(repoRoot, filePath) {
  const relative = path.relative(repoRoot, filePath).split(path.sep).join("/");
  if (!relative || relative === ".." || relative.startsWith("../") || path.posix.isAbsolute(relative)) {
    throw new StructureError("Worker debt catalogue must be inside the repository for provenance checking");
  }
  return relative;
}

export function loadTrustedBaseline(repoRoot, configPath, baselineRef, today) {
  const eventBaseCommit = resolveCommit(repoRoot, baselineRef);
  if (!gitSucceeds(repoRoot, ["merge-base", "--is-ancestor", eventBaseCommit, "HEAD"])) {
    throw new StructureError(
      `trusted baseline ${eventBaseCommit} is not an ancestor of HEAD; provenance is ambiguous`,
    );
  }
  const configRelative = repositoryPath(repoRoot, configPath);
  const checkerObject = `${eventBaseCommit}:apps/worker/scripts/check-structure.mjs`;
  let catalogueCommit = eventBaseCommit;
  let configObject = `${catalogueCommit}:${configRelative}`;
  if (!gitObjectExists(repoRoot, configObject)) {
    if (gitObjectExists(repoRoot, checkerObject)) {
      throw new StructureError(
        `trusted baseline ${eventBaseCommit} contains the Worker structure gate but no ${configRelative}`,
      );
    }
    const additions = gitOutput(
      repoRoot,
      [
        "log",
        "--format=%H",
        "--diff-filter=A",
        "--reverse",
        "--topo-order",
        `${eventBaseCommit}..HEAD`,
        "--",
        configRelative,
      ],
      `cannot find the first Worker debt catalogue after ${eventBaseCommit}`,
    ).split("\n").filter(Boolean);
    if (!additions.length) {
      return { commit: eventBaseCommit, eventBaseCommit, state: "bootstrap", exemptions: null };
    }
    catalogueCommit = resolveCommit(repoRoot, additions[0]);
    configObject = `${catalogueCommit}:${configRelative}`;
    if (!gitObjectExists(repoRoot, configObject)) {
      throw new StructureError(`first Worker debt catalogue commit ${catalogueCommit} has no readable catalogue`);
    }
  }
  const text = gitOutput(
    repoRoot,
    ["cat-file", "-p", configObject],
    `cannot read Worker debt catalogue from trusted baseline ${catalogueCommit}`,
  );
  // A prior expiry may legitimately be renewed by the current exact catalogue;
  // the current load still rejects expired debt. All other prior metadata and
  // metrics remain strictly parsed.
  const exemptions = parseConfigDocument(text, "0000-01-01", `trusted baseline ${catalogueCommit}`);
  return {
    commit: catalogueCommit,
    eventBaseCommit,
    state: catalogueCommit === eventBaseCommit ? "enforced" : "bootstrap-anchored",
    exemptions,
  };
}

export function checkRepository({
  repoRoot = DEFAULT_ROOT,
  configPath,
  today,
  minimumFiles,
  baselineRef,
  enforceProvenance,
} = {}) {
  try {
    const root = path.resolve(repoRoot);
    const resolvedConfig = path.resolve(configPath ?? path.join(root, DEFAULT_CONFIG));
    const metrics = scanTree(root, minimumFiles ?? MINIMUM_SOURCE_FILES);
    const exemptions = loadConfig(resolvedConfig, today ?? currentLocalDate());
    const errors = evaluate(metrics, exemptions);
    let baseline = null;
    const provenanceRequired = enforceProvenance ?? (configPath === undefined || baselineRef !== undefined);
    if (provenanceRequired) {
      const trustedRef = baselineRef ?? resolveTrustedBaselineRef(root);
      baseline = loadTrustedBaseline(root, resolvedConfig, trustedRef, today ?? currentLocalDate());
      if (baseline.exemptions) errors.push(...evaluateTrustedBaseline(exemptions, baseline.exemptions));
    }
    return { metrics, exemptions, baseline, errors };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { metrics: [], exemptions: {}, baseline: null, errors: [message] };
  }
}

export function candidateConfig(metrics, { owner, reason, expires }) {
  const exemptions = {};
  for (const metric of metrics.filter(isFileViolation)) {
    exemptions[metric.path] = {
      file_lines: metric.file_lines,
      max_function_lines: metric.max_function_lines,
      max_parameters: metric.max_parameters,
      max_complexity: metric.max_complexity,
      max_nesting_depth: metric.max_nesting_depth,
      over_limit_functions: overLimitFunctions(metric),
      owner,
      reason,
      expires,
    };
  }
  return { version: CONFIG_VERSION, limits: LIMITS, exemptions };
}

function parseArguments(argv) {
  const result = { repoRoot: DEFAULT_ROOT, minimumFiles: MINIMUM_SOURCE_FILES, candidate: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--candidate") result.candidate = true;
    else if (["--root", "--config", "--today", "--minimum-files", "--baseline-ref"].includes(argument)) {
      const value = argv[index + 1];
      if (!value) throw new StructureError(`${argument} requires a value`);
      index += 1;
      if (argument === "--root") result.repoRoot = value;
      if (argument === "--config") result.configPath = value;
      if (argument === "--today") result.today = value;
      if (argument === "--minimum-files") result.minimumFiles = Number(value);
      if (argument === "--baseline-ref") result.baselineRef = value;
    } else throw new StructureError(`unknown argument: ${argument}`);
  }
  if (!isPositiveInteger(result.minimumFiles)) throw new StructureError("--minimum-files must be a positive integer");
  if (result.today !== undefined && !isIsoDate(result.today)) throw new StructureError("--today must be an ISO date");
  return result;
}

function printReport(report) {
  const functionCount = report.metrics.reduce((total, item) => total + item.functions.length, 0);
  console.log("Worker TypeScript structural ratchet");
  console.log(
    `files=${report.metrics.length} functions=${functionCount} ` +
    `limits=file:${LIMITS.max_file_lines},function:${LIMITS.max_function_lines},` +
    `parameters:${LIMITS.max_parameters},complexity:${LIMITS.max_complexity},` +
    `nesting:${LIMITS.max_nesting_depth} ` +
    `debt_files=${Object.keys(report.exemptions).length}`,
  );
  if (report.baseline) {
    console.log(`trusted_baseline=${report.baseline.commit} provenance=${report.baseline.state}`);
  }
  if (report.errors.length) {
    console.error("FAIL:");
    for (const error of report.errors) console.error(`  - ${error}`);
  } else {
    console.log("PASS: no new Worker structural debt and every ratchet matches current source.");
  }
}

function main(argv) {
  let options;
  try {
    options = parseArguments(argv);
    if (options.candidate) {
      const root = path.resolve(options.repoRoot);
      const metrics = scanTree(root, options.minimumFiles);
      const candidate = candidateConfig(metrics, {
        owner: "worker-maintainers",
        reason: "Legacy Worker source debt captured when the TypeScript structural floor became enforceable; reduce by component without semantic reversion.",
        expires: "2026-12-31",
      });
      const configPath = path.resolve(options.configPath ?? path.join(root, DEFAULT_CONFIG));
      const baselineRef = options.baselineRef ?? resolveTrustedBaselineRef(root);
      const baseline = loadTrustedBaseline(root, configPath, baselineRef, options.today ?? currentLocalDate());
      const provenanceErrors = baseline.exemptions
        ? evaluateTrustedBaseline(candidate.exemptions, baseline.exemptions)
        : [];
      if (provenanceErrors.length) {
        throw new StructureError(
          `candidate would self-approve structural debt:\n  - ${provenanceErrors.join("\n  - ")}`,
        );
      }
      console.log(`${JSON.stringify(candidate, null, 2)}\n`);
      return 0;
    }
  } catch (error) {
    console.error(`FAIL: ${error instanceof Error ? error.message : String(error)}`);
    return 1;
  }
  const report = checkRepository(options);
  printReport(report);
  return report.errors.length ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
