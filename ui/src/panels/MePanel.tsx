// Round Three personal surface (any authenticated user). A lightweight personal
// dashboard: the one thing that lives HERE is invoking your personal agent
// (delegated-only: it runs on-behalf-of you and is capped to your grants - the
// returned effective_grants show that cap, SEC-30). Everything editable -
// configuring the agent, notification routing, memory - is edited in ONE home
// (Settings / Ops); this panel links there instead of shipping a second editor.

import { useState } from "react";
import type { ReactNode } from "react";

import { api } from "../api/client";
import type { SpawnResult } from "../api/types";
import { navigate } from "../router";
import { CodeBlock, GrantList, errText } from "./shared";
import { Field, Hint, InfoCallout, PageIntro } from "./ux";

function AskYourAgent() {
  const [message, setMessage] = useState("");
  const [invBusy, setInvBusy] = useState(false);
  const [invError, setInvError] = useState<string | null>(null);
  const [invResult, setInvResult] = useState<SpawnResult | null>(null);

  async function invoke() {
    if (!message.trim()) {
      setInvError("A message is required.");
      return;
    }
    setInvBusy(true);
    setInvError(null);
    setInvResult(null);
    try {
      const res = await api.invokePersonalAgent({ message: message.trim() });
      setInvResult(res);
    } catch (err) {
      setInvError(errText(err));
    } finally {
      setInvBusy(false);
    }
  }

  return (
    <div className="form">
      <div className="form__title">Ask your agent</div>
      <InfoCallout>
        It runs on your behalf and can never do more than you can - the
        permissions it used are shown below as <code>effective_grants</code>.
      </InfoCallout>
      <Field label="Message" hint="What should your agent do?" example="Draft a reply to ticket 4821">
        <textarea
          className="code"
          value={message}
          onChange={(e) => setMessage(e.target.value)}
        />
      </Field>
      <div className="form__actions">
        <button className="btn btn--primary" disabled={invBusy} onClick={invoke}>
          {invBusy ? "Working..." : "Ask"}
        </button>
        {invError && <span className="error">{invError}</span>}
      </div>
      {invResult &&
        (invResult.error || invResult.status === "denied" ? (
          <p className="error">
            {String(invResult.error ?? invResult.reason ?? "no_personal_agent")}
          </p>
        ) : (
          <div className="stack">
            <div className="row-line">
              <span className="muted">effective_grants</span>
              <GrantList grants={invResult.effective_grants} />
            </div>
            <CodeBlock value={invResult} />
          </div>
        ))}
    </div>
  );
}

// A signpost card into the single editor home for one preference area (no second
// editor is shipped here).
function LinkCard({
  title,
  body,
  to,
  cta,
}: {
  title: ReactNode;
  body: ReactNode;
  to: string;
  cta: string;
}) {
  return (
    <div className="form">
      <div className="form__title">{title}</div>
      <Hint>{body}</Hint>
      <div className="form__actions">
        <button className="btn" onClick={() => navigate(to)}>
          {cta}
        </button>
      </div>
    </div>
  );
}

export function MePanel() {
  return (
    <section className="panel">
      <PageIntro
        title="Me"
        lead="Ask your personal agent, and jump to your personal settings."
        howToggle
        how="Your agent runs as you and never exceeds your permissions. Configuring it, your notifications and your memory each have one home - this page links you straight there."
      />

      <div className="cols">
        <AskYourAgent />
        <div className="stack">
          <LinkCard
            title="Your personal agent"
            body="Configure the assistant that runs as you - its runtime and the skills it may use."
            to="/settings/agent"
            cta="Configure in Settings"
          />
          <LinkCard
            title="Notifications"
            body="Choose how and when Boltrig reaches you - approvals, escalations and more."
            to="/settings/notifications"
            cta="Manage in Settings"
          />
          <LinkCard
            title="Memory"
            body="Browse and search what Boltrig remembers within your scope (SEC-31)."
            to="/memory"
            cta="Open Memory"
          />
        </div>
      </div>
    </section>
  );
}
