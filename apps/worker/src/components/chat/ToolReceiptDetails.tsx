import { useEffect, useMemo, useState } from "react";
import {
  normalizeEvents,
  type ToolEntry,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../../client";
import { isCommandTool, toolActionLabel } from "./toolVerbPresentation";

interface ToolReceiptDetailsProps {
  runId?: string;
  tools: ToolEntry[];
}

type DetailLoadState = "bounded" | "loading" | "ready" | "unavailable";

const MAX_PAYLOAD_CHARS = 12_000;

function toolIdentity(tool: ToolEntry, index: number): string {
  return `${tool.callId ?? tool.key}\u001f${index}`;
}

function mergeDetailedTools(bounded: ToolEntry[], detailed: ToolEntry[]): ToolEntry[] {
  const used = new Set<number>();
  return bounded.map((tool) => {
    let matchIndex = tool.callId
      ? detailed.findIndex((candidate, index) => (
        !used.has(index) && candidate.callId === tool.callId
      ))
      : -1;
    if (matchIndex < 0) {
      matchIndex = detailed.findIndex((candidate, index) => (
        !used.has(index) && candidate.verb === tool.verb
      ));
    }
    if (matchIndex < 0) return tool;
    used.add(matchIndex);
    const match = detailed[matchIndex]!;
    return {
      ...tool,
      argKeys: match.argKeys?.length ? match.argKeys : tool.argKeys,
      argCount: match.argCount ?? tool.argCount,
      input: match.input ?? tool.input,
      output: match.output ?? tool.output,
      resultKeys: match.resultKeys?.length ? match.resultKeys : tool.resultKeys,
      status: match.status === "pending" ? tool.status : match.status,
    };
  });
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function stringValue(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return value.join(" ");
  }
  return null;
}

function commandText(input: unknown): string | null {
  const direct = stringValue(input);
  if (direct) return direct;
  const source = record(input);
  if (!source) return null;
  for (const key of ["cmd", "command", "script", "argv"]) {
    const value = stringValue(source[key]);
    if (value) return value;
  }
  return null;
}

function terminalOutput(output: unknown): string | null {
  const direct = stringValue(output);
  if (direct) return direct;
  const source = record(output);
  if (!source) return null;
  const chunks: string[] = [];
  for (const key of ["output", "stdout", "stderr", "text"]) {
    const value = stringValue(source[key]);
    if (!value) continue;
    chunks.push(key === "output" || key === "text" ? value : `${key}\n${value}`);
  }
  return chunks.length > 0 ? chunks.join("\n") : null;
}

function payloadText(value: unknown): string | null {
  if (value === undefined) return null;
  let text: string;
  try {
    text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  } catch {
    return "[detail could not be rendered]";
  }
  if (text.length <= MAX_PAYLOAD_CHARS) return text;
  return `${text.slice(0, MAX_PAYLOAD_CHARS)}\n… detail clipped`;
}

function statusPresentation(status: string): { glyph: string; label: string; tone: string } {
  if (status === "ok") return { glyph: "✓", label: "Success", tone: "ok" };
  if (status === "pending") return { glyph: "", label: "Working", tone: "pending" };
  if (status === "pending_human") {
    return { glyph: "", label: "Waiting for approval", tone: "pending_human" };
  }
  if (status === "degraded") return { glyph: "!", label: "Degraded", tone: "degraded" };
  return { glyph: "×", label: status.replaceAll("_", " "), tone: "error" };
}

function FieldSummary({ label, keys }: { label: string; keys?: string[] }) {
  if (!keys?.length) return null;
  return (
    <p className="transcript-tool-field-summary">
      <span>{label}</span>
      {keys.join(", ")}
    </p>
  );
}

function PayloadBlock({ label, value }: { label: string; value: unknown }) {
  const text = payloadText(value);
  if (text == null) return null;
  return (
    <section className="transcript-tool-payload">
      <h4>{label}</h4>
      <pre><code>{text}</code></pre>
    </section>
  );
}

function ToolEvidencePanel({ tool }: { tool: ToolEntry }) {
  const status = statusPresentation(tool.status);
  const command = isCommandTool(tool.verb) ? commandText(tool.input) : null;
  const output = command ? terminalOutput(tool.output) : null;
  return (
    <section
      aria-label={`${tool.verb} execution detail`}
      className="transcript-tool-evidence"
    >
      {command ? (
        <section className="transcript-tool-terminal">
          <h4>Shell</h4>
          <pre><code>{`$ ${command}${output ? `\n${output}` : ""}`}</code></pre>
        </section>
      ) : (
        <>
          <PayloadBlock label="Input" value={tool.input} />
          <PayloadBlock label="Result" value={tool.output} />
        </>
      )}
      <FieldSummary label="Input fields" keys={tool.argKeys} />
      <FieldSummary label="Result fields" keys={tool.resultKeys} />
      <div className="transcript-tool-outcome" data-status={status.tone}>
        {status.glyph && <span aria-hidden>{status.glyph}</span>}
        {status.label}
      </div>
    </section>
  );
}

export function ToolReceiptDetails({ runId, tools }: ToolReceiptDetailsProps) {
  const [snapshot, setSnapshot] = useState<ToolEntry[] | null>(null);
  const [loadState, setLoadState] = useState<DetailLoadState>("bounded");
  const detailedTools = useMemo(
    () => snapshot ? mergeDetailedTools(tools, snapshot) : tools,
    [snapshot, tools],
  );
  const identities = detailedTools.map(toolIdentity).join("\u001e");
  const [selected, setSelected] = useState(() => toolIdentity(tools[0]!, 0));

  useEffect(() => {
    if (detailedTools.some((tool, index) => toolIdentity(tool, index) === selected)) return;
    setSelected(toolIdentity(detailedTools[0]!, 0));
  }, [detailedTools, identities, selected]);

  useEffect(() => {
    setSnapshot(null);
    if (!runId) {
      setLoadState("bounded");
      return undefined;
    }
    const controller = new AbortController();
    setLoadState("loading");
    void client.runEvents(runId, controller.signal).then((events) => {
      if (controller.signal.aborted) return;
      setSnapshot(normalizeEvents(events).tools);
      setLoadState("ready");
    }).catch(() => {
      if (!controller.signal.aborted) setLoadState("unavailable");
    });
    return () => controller.abort();
  }, [runId]);

  const activeIndex = detailedTools.findIndex(
    (tool, index) => toolIdentity(tool, index) === selected,
  );
  const active = detailedTools[activeIndex < 0 ? 0 : activeIndex];
  return (
    <div className="transcript-tool-details">
      <div aria-label="Exact tool details" className="transcript-tool-list" role="list">
        {detailedTools.map((tool, index) => {
          const id = toolIdentity(tool, index);
          const status = statusPresentation(tool.status);
          return (
            <div className="transcript-tool-detail" key={id} role="listitem">
              <button
                aria-pressed={id === selected}
                onClick={() => setSelected(id)}
                type="button"
              >
                <span className="transcript-tool-detail-copy">
                  <strong>{toolActionLabel(tool.verb)}</strong>
                  <code>{tool.verb}</code>
                </span>
                <span data-status={status.tone}>{status.label}</span>
              </button>
            </div>
          );
        })}
      </div>
      {loadState === "loading" && (
        <p className="transcript-tool-load-state" role="status">Loading detailed receipt…</p>
      )}
      {loadState === "unavailable" && (
        <p className="transcript-tool-load-state">Detailed receipt unavailable; showing bounded fields.</p>
      )}
      {active && <ToolEvidencePanel tool={active} />}
    </div>
  );
}
