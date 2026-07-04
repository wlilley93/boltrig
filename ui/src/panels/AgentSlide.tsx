import { navigate } from "../router";
import { useAgentSlide } from "./agentSlide/useAgentSlide";
import { BudgetMeter } from "./agentSlide/BudgetMeter";
import {
  AgentCallableSection,
  AgentFulfilsSection,
  AgentModelSection,
  AgentSkillsSection,
  AgentWorkSection,
} from "./agentSlide/AgentSlideSections";
import {
  AgentSlideDenied,
  AgentSlideFooter,
  AgentSlideNotFound,
  AgentSlideProfile,
} from "./agentSlide/AgentSlideChrome";
import { FetchError, InfoCallout, PageIntro } from "./ux";

export function AgentSlide({ agentName }: { agentName: string }) {
  const s = useAgentSlide(agentName);

  if (s.loading) {
    return <section className="panel ag-detail"><p className="muted">Loading agent...</p></section>;
  }
  if (s.denied) {
    return <AgentSlideDenied denied={s.denied} />;
  }

  const agent = s.agent;
  const draft = s.draft;
  const preview = s.preview;
  if (!agent || !draft || !preview) {
    return <AgentSlideNotFound agentName={agentName} />;
  }

  return (
    <section className="panel ag-detail">
      <PageIntro
        title={<><code>{agent.name}</code> <span className="badge">{agent.kind}</span></>}
        lead="Inspect what this agent can do and request governed changes to its live capability profile."
        how="Hierarchy placement is config-backed. Capability profile changes are live for future spawns once the approval is applied."
        actions={<button className="btn" onClick={() => navigate("/agents")}>Back to org</button>}
      />

      <FetchError error={s.skillsError} status={s.skillsErrorStatus} onRetry={s.skillsReload} />
      <FetchError error={s.capsError} status={s.capsErrorStatus} onRetry={s.capsReload} />

      {(agent.kind === "chief" || agent.kind === "head") && (
        <InfoCallout title="Hierarchy config is read-only here">
          This slide can request a live capability change through the kernel.
          Moving departments or rewriting hierarchy config stays in Admin until
          the org-config verb lands.
        </InfoCallout>
      )}

      <AgentSlideProfile agent={agent} preview={preview} />

      <div className="ag-detail-grid">
        <AgentSkillsSection draft={draft} preview={preview} skillOptions={s.skillOptions} update={s.update} />
        <AgentModelSection draft={draft} runtimes={s.runtimes} modelEndpoints={s.modelEndpoints} update={s.update} />
        <AgentFulfilsSection verbs={preview.boundVerbs} />
        <AgentCallableSection verbs={preview.effectiveVerbs} />
        <section className="ag-section">
          <h3>Budget</h3>
          <BudgetMeter budget={preview.budget} />
        </section>
        <AgentWorkSection items={preview.workItems} />
      </div>

      <AgentSlideFooter
        jsonText={s.jsonText}
        jsonError={s.jsonError}
        error={s.error}
        pending={s.pending}
        dirty={s.dirty}
        saving={s.saving}
        agentName={agent.name}
        updateJson={s.updateJson}
        onApplied={s.onApplied}
        onDenied={s.onDenied}
        onSave={() => void s.save()}
        onDiscard={s.discard}
      />
    </section>
  );
}
