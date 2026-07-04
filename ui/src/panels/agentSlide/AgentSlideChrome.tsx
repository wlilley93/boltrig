import type { ReactNode } from "react";

import { navigate } from "../../router";
import type { InvokeResult } from "../../api/types";
import type { AgentModel } from "../agents/model";
import { EmptyState, InfoCallout, PageIntro } from "../ux";
import { JsonDisclosure } from "../uxForm";
import { PendingHumanCard, SaveBar } from "../uxFlow";
import type { AgentParams } from "./types";

export function AgentSlideProfile({
  agent,
  preview,
}: {
  agent: AgentModel;
  preview: AgentModel;
}) {
  return (
    <div className="ag-profile">
      <div>
        <span className={`ag-profile__accent ag-profile__accent--${agent.kind}`} />
        <h3><code>{agent.name}</code></h3>
        <p>
          {agent.department ? `${agent.department} department. ` : ""}
          {agent.runtime} runtime, {agent.model_endpoint ?? "default model"},
          depth {agent.max_depth}, {agent.cost_tier} cost tier.
        </p>
      </div>
      <div className="ag-profile__badges">
        <span className="badge">{agent.is_ephemeral ? "ephemeral" : "durable"}</span>
        <span className="badge">{preview.matchedSkills.length} matched skills</span>
        <span className="badge">{preview.effectiveVerbs.length} callable verbs</span>
      </div>
    </div>
  );
}

export function AgentSlideDenied({ denied }: { denied: string }) {
  return (
    <section className="panel ag-detail">
      <PageIntro title="Agents" />
      <InfoCallout tone="warn" title="No access to this agent">
        The server declined the org read ({denied}). Ask an admin to widen
        your access.
      </InfoCallout>
    </section>
  );
}

export function AgentSlideNotFound({ agentName }: { agentName: string }) {
  return (
    <section className="panel ag-detail">
      <EmptyState
        title="Agent not found"
        body={`No configured agent named ${agentName} is visible to this identity.`}
        action={<button className="btn" onClick={() => navigate("/agents")}>Back to org</button>}
      />
    </section>
  );
}

export function AgentSlideFooter({
  jsonText,
  jsonError,
  error,
  pending,
  dirty,
  saving,
  agentName,
  updateJson,
  onApplied,
  onDenied,
  onSave,
  onDiscard,
}: {
  jsonText: string;
  jsonError: string | null;
  error: string | null;
  pending: { id: string; params: AgentParams } | null;
  dirty: boolean;
  saving: boolean;
  agentName: string;
  updateJson: (text: string) => void;
  onApplied: (result: InvokeResult) => void;
  onDenied: (reason: string) => void;
  onSave: () => void;
  onDiscard: () => void;
}): ReactNode {
  return (
    <>
      <JsonDisclosure
        value={jsonText}
        onChange={updateJson}
        error={jsonError}
        summaryNote="control.capability.upsert params"
      />
      {jsonError && <InfoCallout tone="warn">{jsonError}</InfoCallout>}
      {error && <InfoCallout tone="warn">{error}</InfoCallout>}
      {pending && (
        <PendingHumanCard
          hitlRequestId={pending.id}
          noun="control"
          verb="control.capability.upsert"
          sentParams={pending.params}
          onApplied={onApplied}
          onDenied={onDenied}
        />
      )}
      <SaveBar
        dirty={dirty}
        saving={saving}
        label={<>Unsaved changes to <code>{agentName}</code></>}
        saveLabel="Save"
        governed
        onSave={onSave}
        onDiscard={onDiscard}
      />
    </>
  );
}
