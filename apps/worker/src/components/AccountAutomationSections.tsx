import { useEffect, useState } from "react";
import type {
  DeleteAck,
  GovernedRouteResponse,
  MeNotificationItem,
  NotificationCatalogue,
  PersonalAgentView,
  PutMeNotificationRequest,
  SpawnResult,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import {
  ExactApprovalFinalizer,
  governedResultReason,
  useExactApprovalFinalizer,
} from "./ExactApprovalFinalizer";

type NotificationMutation = {
  kind: "save" | "toggle";
  body: PutMeNotificationRequest;
  success: string;
};

export function NotificationPreferences() {
  const [prefs, setPrefs] = useState<MeNotificationItem[]>([]);
  const [catalogue, setCatalogue] = useState<NotificationCatalogue>({
    events: [],
    transports: [],
  });
  const [eventType, setEventType] = useState("");
  const [channel, setChannel] = useState("");
  const [target, setTarget] = useState("");
  const [message, setMessage] = useState("");

  const finalizer = useExactApprovalFinalizer<
    NotificationMutation,
    GovernedRouteResponse<DeleteAck>
  >({
    isCurrent: (input) => {
      if (input.kind === "save") {
        return routeInputEquals(input.body, notificationDraft(
          eventType, channel, target, true,
        ));
      }
      const pref = prefs.find((item) => item.id === input.body.id);
      return pref !== undefined
        && routeInputEquals(input.body, {
          id: pref.id,
          event_type: pref.event_type,
          channel: pref.channel,
          target: pref.target,
          enabled: !pref.enabled,
        });
    },
    replay: (input, approvalId) => (
      client.putMeNotification(input.body, approvalId)
    ),
    onApplied: async (_result, input) => {
      setMessage(input.success);
      refresh();
    },
    onRefused: (result) => {
      setMessage(governedResultReason(
        result, "The approved notification change was refused.",
      ));
    },
  });

  function refresh() {
    finalizer.invalidate();
    void client.meNotifications()
      .then((result) => {
        setPrefs(result.prefs);
        setCatalogue(result.catalogue);
        setEventType((current) => (
          result.catalogue.events.some((item) => item.id === current)
            ? current
            : result.catalogue.events[0]?.id ?? ""
        ));
        const transport = (
          result.catalogue.transports.find((item) => item.id === channel)
          ?? result.catalogue.transports[0]
        );
        setChannel(transport?.id ?? "");
        setTarget(transport?.targets[0]?.id ?? "");
      })
      .catch(() => setMessage("Notification preferences are unavailable."));
  }

  useEffect(refresh, []);

  async function save() {
    const input: NotificationMutation = {
      kind: "save",
      body: notificationDraft(eventType, channel, target, true),
      success: "Notification route saved.",
    };
    const result = await client.putMeNotification(input.body);
    if (finalizer.begin(input, result, "Notification route change")) {
      setMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    setMessage(outcomeMessage(result, input.success));
    if (result.status === "ok") refresh();
  }

  async function test(pref: MeNotificationItem) {
    const result = await client.testMeNotification(pref.id);
    setMessage(
      result.status === "ok" && result.delivery_status === "queued"
        ? "Test queued. Delivery remains pending until the channel gateway acknowledges it."
        : outcomeMessage(result, "Test accepted."),
    );
    if (result.status === "ok") refresh();
  }

  async function toggle(pref: MeNotificationItem) {
    const input: NotificationMutation = {
      kind: "toggle",
      body: {
        id: pref.id,
        event_type: pref.event_type,
        channel: pref.channel,
        target: pref.target,
        enabled: !pref.enabled,
      },
      success: pref.enabled ? "Route disabled." : "Route enabled.",
    };
    const result = await client.putMeNotification(input.body);
    if (finalizer.begin(input, result, "Notification route change")) {
      setMessage("Pending approval. Continue in the originating chat.");
      return;
    }
    setMessage(outcomeMessage(result, input.success));
    if (result.status === "ok") refresh();
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Notifications</p>
      <h2>Routes for events that need you</h2>
      <p className="muted small">
        Events and destinations come from the server’s live delivery catalogue.
      </p>
      <select
        className="field-control"
        aria-label="Notification event"
        value={eventType}
        onChange={(event) => {
          finalizer.invalidate();
          setEventType(event.target.value);
        }}
      >
        {catalogue.events.map((item) => (
          <option value={item.id} key={item.id}>{item.label}</option>
        ))}
      </select>
      <select
        className="field-control"
        aria-label="Notification channel"
        value={channel}
        onChange={(event) => {
          finalizer.invalidate();
          const transport = catalogue.transports.find(
            (item) => item.id === event.target.value
          );
          setChannel(event.target.value);
          setTarget(transport?.targets[0]?.id ?? "");
        }}
      >
        {catalogue.transports.map((item) => (
          <option value={item.id} key={item.id}>
            {item.label} · {item.platform}
          </option>
        ))}
      </select>
      <select
        className="field-control"
        aria-label="Notification target"
        value={target}
        onChange={(event) => {
          finalizer.invalidate();
          setTarget(event.target.value);
        }}
      >
        {(catalogue.transports.find((item) => item.id === channel)?.targets ?? [])
          .map((item) => (
            <option value={item.id} key={item.id}>{item.label}</option>
          ))}
      </select>
      {catalogue.transports.length === 0 && (
        <p className="notice">
          No verified connected channel can currently deliver notifications to you.
          In-app and email delivery are not configured.
        </p>
      )}
      <button
        className="primary-button"
        disabled={!eventType || !channel || !target}
        onClick={() => void save()}
      >
        Add route
      </button>
      <div className="data-list" aria-label="Notification routes">
        {prefs.map((pref) => (
          <div className="data-row" key={pref.id}>
            <span className={`activity-dot ${pref.enabled ? "done" : "failed"}`} />
            <span className="data-row-copy">
              <strong>
                {catalogue.events.find((item) => item.id === pref.event_type)?.label
                  ?? pref.event_type}
              </strong>
              <small>
                {catalogue.transports.find((item) => item.id === pref.channel)?.label
                  ?? pref.channel}
                {pref.target ? ` · ${pref.target}` : ""}
                {" · "}
                {pref.last_delivery
                  ? `last delivery ${pref.last_delivery.status.replaceAll("_", " ")}`
                  : "not tested or delivered yet"}
              </small>
            </span>
            <div className="inline-actions">
              {!pref.deliverable && <span className="row-meta">unavailable</span>}
              <button
                className="secondary-button"
                disabled={!pref.enabled || !pref.deliverable}
                onClick={() => void test(pref)}
              >
                Test
              </button>
              <button className="secondary-button" onClick={() => void toggle(pref)}>
                {pref.enabled ? "Disable" : "Enable"}
              </button>
            </div>
          </div>
        ))}
      </div>
      <ExactApprovalFinalizer controller={finalizer} />
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

export function PersonalAgentLifecycle() {
  const [agent, setAgent] = useState<PersonalAgentView | null>(null);
  const [runtime, setRuntime] = useState("codex");
  const [skills, setSkills] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [task, setTask] = useState("");
  const [lastRun, setLastRun] = useState<SpawnResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  function refresh() {
    void client.meAgent()
      .then((result) => {
        setAgent(result.agent ?? null);
        if (result.agent) {
          // Worker is the Codex-primary surface. A legacy deterministic
          // fallback remains readable for migration, but a replacement from
          // this surface always moves the personal agent onto Codex.
          setRuntime("codex");
          setSkills(result.agent.skills.join(", "));
        }
      })
      .catch(() => setAgent(null));
  }

  useEffect(refresh, []);

  async function configure() {
    const result = await client.configurePersonalAgent({
      runtime,
      skills: skills.split(",").map((item) => item.trim()).filter(Boolean),
    });
    setMessage(result.status === "ok" ? "Personal agent configured." : "Configuration denied.");
    if (result.status === "ok") refresh();
  }

  async function remove() {
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    const result = await client.deletePersonalAgent();
    setMessage(result.status === "ok" ? "Personal agent deleted." : result.reason ?? result.status);
    setDeleteArmed(false);
    if (result.status === "ok") refresh();
  }

  async function invokeAgent(event: React.FormEvent) {
    event.preventDefault();
    if (!task.trim() || busy) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await client.invokePersonalAgent({ message: task.trim() });
      setLastRun(result);
      setMessage(result.run_id
        ? `Personal agent started run ${result.run_id}.`
        : result.reason ?? `Personal agent returned ${result.status ?? "without a run"}.`);
      if (result.run_id) setTask("");
    } catch {
      setMessage("The personal agent could not be invoked.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card">
      <p className="eyebrow">Personal agent</p>
      <h2>{agent ? "Your delegated agent" : "Create a delegated agent"}</h2>
      <p>It acts on your behalf and cannot exceed your current server-side grants.</p>
      {agent && (
        <dl className="fact-grid">
          <div><dt>Runtime</dt><dd>{agent.runtime}</dd></div>
          <div><dt>Status</dt><dd>{agent.enabled ? "enabled" : "disabled"}</dd></div>
        </dl>
      )}
      <select
        className="field-control"
        aria-label="Personal agent runtime"
        value={runtime}
        onChange={(event) => setRuntime(event.target.value)}
      >
        <option value="codex">Codex</option>
      </select>
      {agent && agent.runtime !== "codex" && (
        <p className="muted small">This legacy {agent.runtime} configuration remains visible; replacing it here migrates the agent to Codex.</p>
      )}
      <input
        className="field-control"
        aria-label="Personal agent skills"
        placeholder="Optional comma-separated approved skills"
        value={skills}
        onChange={(event) => setSkills(event.target.value)}
      />
      <button className="primary-button" onClick={() => void configure()}>
        {agent ? "Replace configuration" : "Create agent"}
      </button>
      {agent && (
        <form className="detail-section author-form" onSubmit={(event) => void invokeAgent(event)}>
          <p className="eyebrow">Delegate a task</p>
          <label><span>Task</span><textarea className="field-control" rows={4} value={task} onChange={(event) => setTask(event.target.value)} /></label>
          <button className="secondary-button" disabled={busy || !task.trim()}>{busy ? "Convening…" : "Ask personal agent"}</button>
          {lastRun?.effective_grants && <div className="skill-list" aria-label="Personal agent effective grants">{lastRun.effective_grants.map((grant) => <span key={grant}>{grant}</span>)}</div>}
          {lastRun?.run_id && <a className="secondary-button" href="#/runs">Inspect run</a>}
        </form>
      )}
      {agent && (
        <button
          className={deleteArmed ? "danger-button armed" : "danger-button"}
          onClick={() => void remove()}
        >
          {deleteArmed ? "Confirm delete agent" : "Delete agent"}
        </button>
      )}
      {message && <p className="notice" role="status">{message}</p>}
    </section>
  );
}

function outcomeMessage(result: { status: string; reason?: string }, success: string): string {
  if (result.status === "ok") return success;
  if (result.status === "pending_human") return "Pending approval. Continue in the originating chat.";
  return result.reason ?? result.status;
}

function notificationDraft(
  eventType: string,
  channel: string,
  target: string,
  enabled: boolean,
): PutMeNotificationRequest {
  return {
    event_type: eventType.trim(),
    channel,
    target: target.trim() || undefined,
    enabled,
  };
}

function routeInputEquals(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}
