import type { ToolEntry } from "@wlilley93/boltrig-web-sdk";

import { integrationForToolVerb } from "./toolActivity";

const FILE_SCOPE = /(^|[._:/-])(file|files|filesystem|fs)([._:/-]|$)/;
const FILE_READ = /(^|[._:/-])(read|list|open|load|get|find|search|glob)([._:/-]|$)/;
const FILE_EDIT = /(^|[._:/-])(write|edit|create|save|append|patch|move|rename|delete|remove)([._:/-]|$)/;
const COMMAND = /(^|[._:/-])(exec|execute|command|shell|terminal|script|bash|zsh)([._:/-]|$)/;

export type ToolGlyphKind = "figma" | "read" | "command" | "generic";

export function toolGlyphKind(tools: ToolEntry[]): ToolGlyphKind {
  const verbs = tools.map((tool) => tool.verb.trim().toLowerCase());
  if (verbs.some((verb) => integrationForToolVerb(verb)?.id === "figma")) return "figma";
  const first = verbs[0] ?? "";
  if (FILE_SCOPE.test(first) && FILE_READ.test(first)) return "read";
  if (COMMAND.test(first)) return "command";
  return "generic";
}

export function isCommandTool(verb: string): boolean {
  return COMMAND.test(verb.trim().toLowerCase());
}

export function toolPhrase(verb: string): string | null {
  const value = verb.trim().toLowerCase();
  const integration = integrationForToolVerb(value);
  if (integration) return `used ${integration.label} integration`;
  if (value === "apply_patch" || (FILE_SCOPE.test(value) && FILE_EDIT.test(value))) {
    return "edited files";
  }
  if (FILE_SCOPE.test(value) && FILE_READ.test(value)) return "read files";
  if (COMMAND.test(value)) return "ran commands";
  if (/web[._:/-](search|query)|search_query/.test(value)) return "searched the web";
  if (/(^|[._:/-])browser([._:/-]|$)/.test(value)) return "used the browser";
  if (/(^|[._:/-])(calendar|schedule|meeting)([._:/-]|$)/.test(value)) {
    return "used calendar tools";
  }
  if (/(^|[._:/-])(mail|email|message|notify)([._:/-]|$)/.test(value)) {
    return "used messaging tools";
  }
  if (/(^|[._:/-])(database|sql|crm|record|table)([._:/-]|$)/.test(value)) {
    return "queried data";
  }
  return null;
}

export function toolActionLabel(verb: string): string {
  const phrase = toolPhrase(verb);
  if (!phrase) return "Used tool";
  return phrase[0]!.toUpperCase() + phrase.slice(1);
}
