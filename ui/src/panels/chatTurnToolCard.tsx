// A compact callout for one tool call. The bounded chat stream shows the verb
// id, the argument KEYS (never values, by design), and a StatusBadge that reads
// "pending" while the call is in flight, then the result status. The run relay
// additionally carries the full input/output, which the Run drawer expands.

import type { ToolEntry } from "@/panels/chatTurnTypes";
import { CONSEQUENCE, StatusBadge, TOOL_STATUS } from "@/panels/ux";

function toolLabel(verb: string): string {
  const clean = verb.replace(/^control\./, "").replace(/\./g, " ");
  return clean.charAt(0).toUpperCase() + clean.slice(1);
}

function toolStatusClass(status: string): string {
  switch (status) {
    case "ok":
      return "tool-card--ok";
    case "pending":
      return "tool-card--running";
    case "pending_human":
    case "paused":
      return "tool-card--paused";
    case "degraded":
      return "tool-card--degraded";
    case "error":
      return "tool-card--denied";
    default:
      return "tool-card--denied";
  }
}

function ToolKeys({ label, keys }: { label: string; keys: string[] }) {
  if (keys.length === 0) return null;
  return (
    <span className="tool-card__keys">
      <span className="muted">{label}</span>
      {keys.map((k) => (
        <code className="chip" key={k}>
          {k}
        </code>
      ))}
    </span>
  );
}

export function ToolCard({ tool }: { tool: ToolEntry }) {
  const resultKeys = tool.resultKeys ?? [];
  const hasIo = tool.input !== undefined || tool.output !== undefined;
  const statusClass = toolStatusClass(tool.status);

  const head = (
    <>
      <span
        className="tool-card__dot"
        aria-hidden="true"
      />
      <span className="tool-card__label">{toolLabel(tool.verb)}</span>
      <code className="badge badge--verb">{tool.verb}</code>
      {tool.consequence && (
        <StatusBadge value={tool.consequence} glossary={CONSEQUENCE} compact />
      )}
      <StatusBadge value={tool.status} glossary={TOOL_STATUS} compact />
      <span className="tool-card__time">{tool.status}</span>
      {hasIo && (
        <span className="tool-card__chevron" aria-hidden="true">
          &#9656;
        </span>
      )}
    </>
  );

  const detail = (
    <div className="tool-card__detail">
      <div>
        verb <span>{tool.verb}</span>
      </div>
      <div>
        receipt <span>{tool.callId ?? tool.key}</span>
      </div>
      <div>
        policy <span>governed through kernel</span>
      </div>
      <div>{tool.status}</div>
      {tool.input !== undefined && (
        <div className="tool-card__payload">
          <span className="tool-card__payload-label">input data</span>
          <pre className="tool-card__output">
            {typeof tool.input === "string" ? tool.input : JSON.stringify(tool.input, null, 2)}
          </pre>
        </div>
      )}
      {tool.output !== undefined && (
        <div className="tool-card__payload">
          <span className="tool-card__payload-label">output data</span>
          <pre className="tool-card__output">
            {typeof tool.output === "string" ? tool.output : JSON.stringify(tool.output, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );

  if (!hasIo) {
    return (
      <div className={`tool-card tool-card--flat ${statusClass}`}>
        <div className="tool-card__head">{head}</div>
        {resultKeys.length > 0 && (
          <div className="tool-card__body">
            <ToolKeys label="result" keys={resultKeys} />
          </div>
        )}
      </div>
    );
  }

  return (
    <details className={`tool-card ${statusClass}`}>
      <summary className="tool-card__head">{head}</summary>
      <div className="tool-card__body">
        {resultKeys.length > 0 && <ToolKeys label="result" keys={resultKeys} />}
        {detail}
      </div>
    </details>
  );
}
