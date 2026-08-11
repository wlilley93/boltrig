import type { NormalizedTurn, ToolEntry } from "@wlilley93/boltrig-web-sdk";

import { integrationForToolVerb } from "./toolActivity";
import "./TranscriptDensity.css";

interface WorkDisclosureProps {
  turn: NormalizedTurn;
  /** Retained for the shared live/settled call site. Tool state, rather than a
      guessed duration, owns the compact transcript summary. */
  settled?: boolean;
  startedAt?: number | null;
  durationSeconds?: number | null;
}

const FILE_SCOPE = /(^|[._:/-])(file|files|filesystem|fs)([._:/-]|$)/;
const FILE_READ = /(^|[._:/-])(read|list|open|load|get|find|search|glob)([._:/-]|$)/;
const FILE_EDIT = /(^|[._:/-])(write|edit|create|save|append|patch|move|rename|delete|remove)([._:/-]|$)/;
const COMMAND = /(^|[._:/-])(exec|execute|command|shell|terminal|script|bash|zsh)([._:/-]|$)/;

type ToolGlyphKind = "figma" | "read" | "command" | "generic";

function toolGlyphKind(tools: ToolEntry[]): ToolGlyphKind {
  const verbs = tools.map((tool) => tool.verb.trim().toLowerCase());
  if (verbs.some((verb) => integrationForToolVerb(verb)?.id === "figma")) return "figma";
  const first = verbs[0] ?? "";
  if (FILE_SCOPE.test(first) && FILE_READ.test(first)) return "read";
  if (COMMAND.test(first)) return "command";
  return "generic";
}

function ToolGlyph({ kind }: { kind: ToolGlyphKind }) {
  return (
    <span
      aria-hidden
      className={`transcript-tool-glyph tool-icon-${kind === "command" ? "terminal" : kind}`}
      data-kind={kind}
    >
      <svg fill="none" viewBox="0 0 24 24">
        {kind === "figma" ? (
          <>
            <path d="M8.5 2H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#f24e1e" />
            <path d="M12 2h3.5a3.5 3.5 0 0 1 0 7H12Z" fill="#ff7262" />
            <path d="M8.5 9H12v7H8.5a3.5 3.5 0 1 1 0-7Z" fill="#a259ff" />
            <circle cx="15.5" cy="12.5" fill="#1abcfe" r="3.5" />
            <path d="M8.5 16H12v3.5A3.5 3.5 0 1 1 8.5 16Z" fill="#0acf83" />
          </>
        ) : kind === "read" ? (
          <>
            <path d="M4.5 4.5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5H4.5Z" />
            <path d="M19.5 4.5h-6a3 3 0 0 0-3 3v12A2.5 2.5 0 0 1 13 17h6.5Z" />
          </>
        ) : kind === "command" ? (
          <>
            <rect height="15" rx="2" width="19" x="2.5" y="4.5" />
            <path d="m7 9 3 3-3 3M13 15h4" />
          </>
        ) : (
          <>
            <rect height="6" rx="1" width="6" x="4" y="4" />
            <rect height="6" rx="1" width="6" x="14" y="4" />
            <rect height="6" rx="1" width="6" x="4" y="14" />
            <rect height="6" rx="1" width="6" x="14" y="14" />
          </>
        )}
      </svg>
    </span>
  );
}

function toolPhrase(verb: string): string | null {
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
  // Exact ids remain available in the expanded audit rows. An unknown verb is
  // not suitable resting-chat copy: exposing it here recreates the diagnostic
  // dump this compact receipt is meant to replace.
  return null;
}

function toolState(tools: ToolEntry[]): { label: string; tone?: "amber" | "red" | "muted" } | null {
  const waiting = tools.filter((tool) => tool.status === "pending_human").length;
  const pending = tools.filter((tool) => tool.status === "pending").length;
  const degraded = tools.filter((tool) => tool.status === "degraded").length;
  const incomplete = tools.filter((tool) => ![
    "ok", "pending", "pending_human", "degraded",
  ].includes(tool.status)).length;
  const labels = [
    waiting > 0 ? "waiting for approval" : "",
    pending > 0 ? "working" : "",
    degraded > 0 ? `${degraded} degraded` : "",
    incomplete > 0 ? `${incomplete} did not complete` : "",
  ].filter(Boolean);
  if (labels.length === 0) return null;
  return {
    label: labels.join(", "),
    tone: incomplete > 0 ? "red" : degraded > 0 || waiting > 0 ? "amber" : "muted",
  };
}

function toolSummary(tools: ToolEntry[]): { text: string; state: ReturnType<typeof toolState> } {
  const classified = tools.map((tool) => toolPhrase(tool.verb));
  const phrases = [...new Set(classified.filter((phrase): phrase is string => Boolean(phrase)))];
  const unknownCount = classified.filter((phrase) => phrase == null).length;
  if (unknownCount > 0) {
    phrases.push(
      phrases.length > 0
        ? `used ${unknownCount} other ${unknownCount === 1 ? "tool" : "tools"}`
        : unknownCount === 1
          ? "used a tool"
          : `used ${unknownCount} tools`,
    );
  }
  const text = phrases.join(", ");
  return {
    text: text ? text[0]!.toUpperCase() + text.slice(1) : "Used tools",
    state: toolState(tools),
  };
}

/** One natural-language transcript row. The bounded stream exposes only tool
 * verb ids and statuses, so the summary classifies those facts conservatively;
 * the native disclosure keeps every exact id/status available without making
 * the resting transcript a stack of diagnostic cards. */
export function WorkDisclosure({ turn }: WorkDisclosureProps) {
  if (turn.tools.length === 0) return null;
  const summary = toolSummary(turn.tools);
  const detailCount = turn.tools.length;
  const glyph = toolGlyphKind(turn.tools);
  return (
    <details className="work-disclosure transcript-tool-disclosure">
      <summary
        aria-label={`${summary.text}${summary.state ? `, ${summary.state.label}` : ""}. ${detailCount} ${detailCount === 1 ? "tool detail" : "tool details"}`}
        className="transcript-tool-summary"
      >
        <ToolGlyph kind={glyph} />
        <span className="transcript-tool-copy">{summary.text}</span>
        {summary.state && (
          <small data-tone={summary.state.tone}>{summary.state.label}</small>
        )}
      </summary>
      <div aria-label="Exact tool details" className="transcript-tool-details" role="list">
        {turn.tools.map((tool, index) => (
          <div className="transcript-tool-detail" key={tool.callId ?? `${tool.key}-${index}`} role="listitem">
            <code>{tool.verb}</code>
            <span data-status={tool.status}>{tool.status}</span>
          </div>
        ))}
      </div>
    </details>
  );
}
