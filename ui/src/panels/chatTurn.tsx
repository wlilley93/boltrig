// Shared rendering of a streamed turn. The same vocabulary (message_start /
// text_delta / reasoning_delta / tool_call / tool_result / subagent / hitl /
// message_end) is produced by POST /v1/chat and by GET /v1/runs/{id}/events, so
// the Chat panel and the Run drawer reduce and render it through this one module
// instead of each rebuilding the cards. normalizeEvents folds the event list
// into a renderable turn; TurnExtras paints the reasoning / tool / sub-agent /
// inline-HITL parts.

import { useState } from "react";

import { api } from "../api/client";
import type { ChatEvent, HITLKind } from "../api/types";
import { apiReason, errText } from "./shared";
import { StatusBadge, TOOL_STATUS } from "./ux";

interface ToolEntry {
  key: string;
  // the correlation id that pairs a tool_call with its tool_result (US-CHAT-10);
  // absent on older run-relay frames, which fall back to verb matching.
  callId?: string;
  verb: string;
  // the argument KEYS only (from args_summary) - never the values, by design.
  argKeys?: string[];
  argCount?: number;
  // "pending" while the call is in flight; then the result status ("ok" |
  // "error" | "degraded" | a reason string).
  status: string;
  // full input/output ride only on the run relay (the Run drawer); the bounded
  // chat stream carries neither, so both are optional.
  input?: unknown;
  output?: unknown;
  resultKeys?: string[];
}

interface QuestionEntry {
  questionId: string;
  prompt: string;
  choices: string[];
}

interface SubagentEntry {
  key: string;
  childRunId: string;
  task: string;
  skills: string[];
}

interface HitlEntry {
  hitlRequestId: string;
  kind: HITLKind;
  question: string;
  options: string[];
}

interface StepEntry {
  stepId: string;
  action: string;
  status: "running" | "ok" | "failed" | "skipped" | "error";
}

export interface NormalizedTurn {
  runId?: string;
  conversationId?: string;
  text: string;
  reasoning: string;
  tools: ToolEntry[];
  subagents: SubagentEntry[];
  hitls: HitlEntry[];
  questions: QuestionEntry[];
  steps: StepEntry[];
  ended: boolean;
  cancelled: boolean;
}

export function normalizeEvents(events: ChatEvent[]): NormalizedTurn {
  let runId: string | undefined;
  let conversationId: string | undefined;
  let text = "";
  let reasoning = "";
  let ended = false;
  let cancelled = false;
  const tools: ToolEntry[] = [];
  const subagents: SubagentEntry[] = [];
  const hitls: HitlEntry[] = [];
  const questions: QuestionEntry[] = [];
  const steps: StepEntry[] = [];
  const stepIndex = new Map<string, StepEntry>(); // fold running -> ok per step_id

  events.forEach((ev, i) => {
    switch (ev.type) {
      case "message_start":
        runId = ev.run_id;
        conversationId = ev.conversation_id;
        break;
      case "text_delta":
        text += ev.delta;
        break;
      case "reasoning_delta":
        reasoning += ev.delta;
        break;
      case "tool_call":
        tools.push({
          key: `t${i}`,
          callId: ev.call_id,
          // the chat stream sends `tool`; the run relay also carries `verb`.
          verb: ev.tool ?? ev.verb ?? "(tool)",
          argKeys: ev.args_summary?.keys ?? [],
          argCount: ev.args_summary?.count,
          input: ev.input,
          status: "pending",
        });
        break;
      case "tool_result": {
        // Pair the result to its call by `call_id` (the correlation id both the
        // chat stream and the run relay now carry). Fall back to the most recent
        // still-pending call of the same verb for older frames without a call_id.
        const byId = ev.call_id
          ? [...tools].reverse().find((t) => t.callId === ev.call_id)
          : undefined;
        const match =
          byId ??
          [...tools]
            .reverse()
            .find((t) => t.status === "pending" && t.verb === (ev.verb ?? ""));
        const resultKeys = ev.result_summary?.keys;
        if (match) {
          match.status = ev.status;
          match.output = ev.output;
          match.resultKeys = resultKeys;
        } else {
          // An unpaired result (rare): render it on its own so nothing is lost.
          tools.push({
            key: `t${i}`,
            callId: ev.call_id,
            verb: ev.verb ?? "(tool)",
            status: ev.status,
            output: ev.output,
            resultKeys,
          });
        }
        break;
      }
      case "subagent":
        subagents.push({
          key: `s${i}`,
          childRunId: ev.child_run_id,
          task: ev.task,
          skills: ev.skills ?? [],
        });
        break;
      case "hitl":
        hitls.push({
          hitlRequestId: ev.hitl_request_id,
          kind: ev.kind,
          question: ev.question,
          options: ev.options ?? [],
        });
        break;
      case "question":
        // The agent is asking the user a clarifying question (US-CHAT-12). It is
        // answered inline via POST /v1/hitl/{question_id}/answer; on success the
        // backend requeues the paused run and the stream resumes.
        questions.push({
          questionId: ev.question_id,
          prompt: ev.prompt,
          choices: ev.choices ?? [],
        });
        break;
      case "workflow_step": {
        // The interpreter emits one event per step transition (running -> ok /
        // failed / skipped). Fold by step_id so each step shows once with its
        // latest status, in first-seen order.
        const existing = stepIndex.get(ev.step_id);
        if (existing) {
          existing.status = ev.status;
          existing.action = ev.action;
        } else {
          const entry: StepEntry = { stepId: ev.step_id, action: ev.action, status: ev.status };
          stepIndex.set(ev.step_id, entry);
          steps.push(entry);
        }
        break;
      }
      case "message_end":
        ended = true;
        runId = ev.run_id ?? runId;
        break;
      case "cancelled":
        // A server-side cancel closes the turn: mark it ended AND cancelled so
        // the surface can badge the (possibly partial) reply as stopped.
        ended = true;
        cancelled = true;
        runId = ev.run_id ?? runId;
        break;
    }
  });

  return {
    runId, conversationId, text, reasoning, tools, subagents, hitls, questions,
    steps, ended, cancelled,
  };
}

function asPretty(value: unknown): string {
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// --- structured-turn sub-views ---------------------------------------------

// A compact callout for one tool call. The bounded chat stream shows the verb
// id, the argument KEYS (never values, by design), and a StatusBadge that reads
// "pending" while the call is in flight, then the result status. The run relay
// additionally carries the full input/output, which the Run drawer expands.
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

function ToolCard({ tool }: { tool: ToolEntry }) {
  const argKeys = tool.argKeys ?? [];
  const resultKeys = tool.resultKeys ?? [];
  // Only the run relay carries the raw input/output; when present, the card is
  // expandable to show them. On the chat stream it is a flat, keys-only callout.
  const hasIo = tool.input !== undefined || tool.output !== undefined;

  const head = (
    <>
      <code className="badge badge--verb">{tool.verb}</code>
      <StatusBadge value={tool.status} glossary={TOOL_STATUS} />
      {argKeys.length > 0 ? (
        <ToolKeys label="args" keys={argKeys} />
      ) : (
        <span className="muted tool-card__keys">no args</span>
      )}
    </>
  );

  if (!hasIo) {
    return (
      <div className="tool-card tool-card--flat">
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
    <details className="tool-card">
      <summary className="tool-card__head">{head}</summary>
      <div className="tool-card__body">
        {resultKeys.length > 0 && <ToolKeys label="result" keys={resultKeys} />}
        {tool.input !== undefined && (
          <div className="tool-card__io">
            <span className="muted">input</span>
            <pre>{asPretty(tool.input)}</pre>
          </div>
        )}
        {tool.output !== undefined && (
          <div className="tool-card__io">
            <span className="muted">output</span>
            <pre>{asPretty(tool.output)}</pre>
          </div>
        )}
      </div>
    </details>
  );
}

// The interpreter's step walk: a compact ordered checklist that mirrors the
// canvas nodes (each step lights as it runs). Distinct from ToolCards, which
// show the underlying verb dispatch a step makes.
function StepsCard({ steps }: { steps: StepEntry[] }) {
  return (
    <div className="steps-card">
      <div className="steps-card__head">
        <span className="badge">workflow</span>
        <span className="muted">{steps.length} step(s)</span>
      </div>
      <ol className="steps-card__list">
        {steps.map((s) => (
          <li className="steps-card__item" key={s.stepId}>
            <span className={`badge badge--tool-${s.status === "failed" ? "error" : s.status}`}>
              {s.status}
            </span>
            <code className="badge badge--verb">{s.action}</code>
          </li>
        ))}
      </ol>
    </div>
  );
}

// When onOpenRun is provided the child run id becomes a handle that raises the
// Run drawer keyed by it, so a viewer can descend the run tree the backbone
// nests (the consumer-side run nesting).
function SubagentCard({
  sub,
  onOpenRun,
}: {
  sub: SubagentEntry;
  onOpenRun?: (runId: string) => void;
}) {
  return (
    <div className="subagent-card">
      <div className="subagent-card__head">
        <span className="badge">sub-agent</span>
        <span className="subagent-card__task">{sub.task || "(no task)"}</span>
      </div>
      {sub.skills.length > 0 && (
        <div className="subagent-card__skills">
          {sub.skills.map((s) => (
            <span className="chip" key={s}>
              {s}
            </span>
          ))}
        </div>
      )}
      {onOpenRun ? (
        <button
          className="run-handle"
          title="Open this sub-agent's run"
          onClick={() => onOpenRun(sub.childRunId)}
        >
          run: <code>{sub.childRunId}</code>
        </button>
      ) : (
        <code className="muted">{sub.childRunId}</code>
      )}
    </div>
  );
}

// Inline HITL. The same request also surfaces in the Approvals panel (one
// shared store), so answering it here resolves it there too, and vice versa.
function ChatHitlCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: HitlEntry;
  resolved: string | undefined;
  onResolve: (id: string, status: string) => void;
}) {
  const [value, setValue] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // approval shows option buttons (falling back to approve/reject); a
  // clarification shows a free-text input.
  const options =
    entry.kind === "approval"
      ? entry.options.length > 0
        ? entry.options
        : ["approve", "reject"]
      : entry.options;

  async function submit(decision: string) {
    if (!decision) {
      setError("Provide a response.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.respondHitl(entry.hitlRequestId, { decision, notes });
      onResolve(entry.hitlRequestId, `recorded (${res.status})`);
    } catch (err) {
      setError(errText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="chat-hitl">
      <div className="chat-hitl__head">
        <span className={`badge badge--type badge--type-${entry.kind}`}>{entry.kind}</span>
        <code className="muted">{entry.hitlRequestId}</code>
      </div>
      <p className="chat-hitl__question">{entry.question || "(no question)"}</p>

      {resolved ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <div className="chat-hitl__respond">
          {entry.kind === "clarification" ? (
            <div className="chat-hitl__row">
              <input
                className="chat-hitl__text"
                placeholder="your answer"
                value={value}
                disabled={busy}
                onChange={(e) => setValue(e.target.value)}
              />
              <button
                className="btn btn--primary"
                disabled={busy}
                onClick={() => submit(value)}
              >
                {busy ? "..." : "Send"}
              </button>
            </div>
          ) : (
            <div className="chat-hitl__options">
              {options.map((opt) => (
                <button key={opt} className="btn" disabled={busy} onClick={() => submit(opt)}>
                  {opt}
                </button>
              ))}
            </div>
          )}
          <textarea
            className="chat-hitl__notes"
            placeholder="notes (optional)"
            value={notes}
            disabled={busy}
            rows={1}
            onChange={(e) => setNotes(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
        </div>
      )}
    </article>
  );
}

// Inline answer card for an agent's clarifying QUESTION (US-CHAT-12). Choices
// (when present) render as one-click options; otherwise a free-text input. A
// submit POSTs to /v1/hitl/{question_id}/answer; on success the answer is shown
// as recorded and the card is disabled, and the backend requeues the paused run
// so the stream resumes. Owner-only is enforced server-side; a 400/403/404/409
// returns {status, reason} which is surfaced in place (never a raw HTTP code).
function ChatQuestionCard({
  entry,
  resolved,
  onResolve,
}: {
  entry: QuestionEntry;
  resolved: string | undefined;
  onResolve: (id: string, answer: string) => void;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasChoices = entry.choices.length > 0;

  async function submit(answer: string) {
    const a = answer.trim();
    if (!a) {
      setError("Provide an answer.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.answerQuestion(entry.questionId, a);
      if (res.status !== "ok") {
        // A denied / not-found / not-a-question / empty answer comes back as a
        // {status, reason} body (tolerateStatus); show the faithful reason.
        setError(res.reason ?? `Answer failed: ${res.status}`);
        return;
      }
      onResolve(entry.questionId, a);
    } catch (err) {
      setError(apiReason(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="chat-hitl chat-question">
      <div className="chat-hitl__head">
        <span className="badge badge--type badge--type-clarification">question</span>
        <code className="muted">{entry.questionId}</code>
      </div>
      <p className="chat-hitl__question">{entry.prompt || "(no question)"}</p>

      {resolved !== undefined ? (
        <p className="ok">Answered: {resolved}</p>
      ) : (
        <div className="chat-hitl__respond">
          {hasChoices ? (
            <div className="chat-hitl__options">
              {entry.choices.map((opt) => (
                <button
                  key={opt}
                  className="btn"
                  disabled={busy}
                  onClick={() => void submit(opt)}
                >
                  {opt}
                </button>
              ))}
            </div>
          ) : (
            <div className="chat-hitl__row">
              <input
                className="chat-hitl__text"
                placeholder="your answer"
                value={value}
                disabled={busy}
                onChange={(e) => setValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void submit(value);
                  }
                }}
              />
              <button
                className="btn btn--primary"
                disabled={busy}
                onClick={() => void submit(value)}
              >
                {busy ? "..." : "Send"}
              </button>
            </div>
          )}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </article>
  );
}

export function TurnExtras({
  turn,
  resolvedHitls,
  onResolve,
  onOpenRun,
}: {
  turn: NormalizedTurn;
  resolvedHitls: Record<string, string>;
  onResolve: (id: string, status: string) => void;
  onOpenRun?: (runId: string) => void;
}) {
  return (
    <>
      {turn.reasoning && (
        <div className="thinking">
          <span className="thinking__label">thinking</span>
          <div className="thinking__body">{turn.reasoning}</div>
        </div>
      )}
      {turn.steps.length > 0 && <StepsCard steps={turn.steps} />}
      {turn.tools.map((t) => (
        <ToolCard key={t.key} tool={t} />
      ))}
      {turn.subagents.map((s) => (
        <SubagentCard key={s.key} sub={s} onOpenRun={onOpenRun} />
      ))}
      {turn.hitls.map((h) => (
        <ChatHitlCard
          key={h.hitlRequestId}
          entry={h}
          resolved={resolvedHitls[h.hitlRequestId]}
          onResolve={onResolve}
        />
      ))}
      {turn.questions.map((q) => (
        <ChatQuestionCard
          key={q.questionId}
          entry={q}
          resolved={resolvedHitls[q.questionId]}
          onResolve={onResolve}
        />
      ))}
    </>
  );
}
