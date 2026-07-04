import type { VerbInfo, WorkItem } from "../../api/types";
import { RunLink } from "../shared";
import { CONSEQUENCE, Field, InfoCallout, StatusBadge, WORK_STATUS } from "../ux";
import type { ChipOption } from "../uxForm";
import { CardSelect, ChipPicker, SegmentedV2, Stepper } from "../uxForm";
import { GrantList } from "../uxFlow";
import type { ModelEndpointOption, AgentModel } from "../agents/model";
import type { AgentParams } from "./types";

export function AgentSkillsSection({
  draft,
  preview,
  skillOptions,
  update,
}: {
  draft: AgentParams;
  preview: AgentModel;
  skillOptions: ChipOption[];
  update: (next: Partial<AgentParams>) => void;
}) {
  return (
    <section className="ag-section">
      <h3>Skills</h3>
      <Field
        label="Skill patterns"
        hint="Patterns like analysis/* include future skills under that path. The preview below shows what matches today."
        meta={`${preview.matchedSkills.length} matches`}
      >
        <ChipPicker
          value={draft.supported_skills}
          onChange={(value) => update({ supported_skills: value })}
          options={skillOptions}
          allowFree
          mono
          ariaLabel="Skill patterns"
          placeholder="Search skills or add a pattern"
          validate={(value) =>
            /^[a-z0-9*][a-z0-9_./*@-]*$/i.test(value)
              ? null
              : "Use skill ids or patterns such as analysis/*."
          }
          emptyHint="Choose exact skills or path patterns."
        />
      </Field>
      {preview.effectiveGrants.length > 0 ? (
        <GrantList grants={preview.effectiveGrants} />
      ) : (
        <p className="muted">No grants are matched by the current skill patterns.</p>
      )}
    </section>
  );
}

export function AgentModelSection({
  draft,
  runtimes,
  modelEndpoints,
  update,
}: {
  draft: AgentParams;
  runtimes: string[];
  modelEndpoints: ModelEndpointOption[];
  update: (next: Partial<AgentParams>) => void;
}) {
  return (
    <section className="ag-section">
      <h3>Model and limits</h3>
      <div className="ag-form-grid">
        <Field label="Runtime" hint="The engine that runs this profile.">
          <select
            value={draft.runtime}
            onChange={(e) => update({ runtime: e.target.value })}
          >
            {runtimes.map((runtime) => (
              <option key={runtime} value={runtime}>{runtime}</option>
            ))}
          </select>
        </Field>
        <Field label="Model endpoint" hint="Endpoint id as configured in the manifest.">
          <select
            value={draft.model_endpoint ?? ""}
            onChange={(e) => update({ model_endpoint: e.target.value || undefined })}
          >
            <option value="">default</option>
            {modelEndpoints.map((m) => (
              <option key={m.id} value={m.id}>
                {m.id}{m.model ? ` (${m.model})` : ""}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Max depth" hint="How many levels of sub-agents this profile may spawn.">
          <Stepper
            value={draft.max_depth}
            min={1}
            max={5}
            unit="levels"
            onChange={(max_depth) => update({ max_depth })}
          />
        </Field>
        <Field label="Ephemeral" hint="Ephemeral profiles are spawned per task and discarded.">
          <SegmentedV2
            value={draft.is_ephemeral ? "yes" : "no"}
            onChange={(value) => update({ is_ephemeral: value === "yes" })}
            options={[
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]}
          />
        </Field>
      </div>
      <Field label="Cost tier" hint="Used by routing and cost policy.">
        <CardSelect
          value={draft.cost_tier}
          onChange={(cost_tier) => update({ cost_tier })}
          options={[
            { value: "cheap", label: "Cheap", body: "Lowest-cost bulk work" },
            { value: "standard", label: "Standard", body: "Default balance" },
            { value: "premium", label: "Premium", body: "Strongest model lane" },
          ]}
        />
      </Field>
    </section>
  );
}

export function VerbTable({ verbs }: { verbs: VerbInfo[] }) {
  return (
    <div className="ag-table">
      {verbs.map((verb) => (
        <div className="ag-table__row" key={verb.id}>
          <code>{verb.id}</code>
          <span>{verb.noun}</span>
          <StatusBadge value={verb.consequence} glossary={CONSEQUENCE} />
        </div>
      ))}
    </div>
  );
}

export function AgentFulfilsSection({ verbs }: { verbs: VerbInfo[] }) {
  return (
    <section className="ag-section">
      <h3>Fulfils these verbs</h3>
      {verbs.length === 0 ? (
        <p className="muted">No visible verbs are bound directly to this agent.</p>
      ) : (
        <VerbTable verbs={verbs} />
      )}
    </section>
  );
}

export function AgentCallableSection({ verbs }: { verbs: VerbInfo[] }) {
  return (
    <section className="ag-section">
      <h3>Can call</h3>
      {verbs.length === 0 ? (
        <p className="muted">No scoped verbs are visible through the matched grants.</p>
      ) : (
        <VerbTable verbs={verbs.slice(0, 18)} />
      )}
      <InfoCallout>
        This list is computed with your own scoped capability read. A parent
        can narrow authority further at spawn time.
      </InfoCallout>
    </section>
  );
}

export function AgentWorkSection({ items }: { items: WorkItem[] }) {
  return (
    <section className="ag-section">
      <h3>Work</h3>
      {items.length === 0 ? (
        <p className="muted">No visible work is owned by this agent's department.</p>
      ) : (
        <div className="ag-table">
          {items.slice(0, 8).map((item) => (
            <div className="ag-table__row" key={item.id}>
              <span>{item.intent}</span>
              <StatusBadge value={item.status} glossary={WORK_STATUS} />
              {item.hatchet_run_id ? (
                <RunLink runId={item.hatchet_run_id} label="run" />
              ) : (
                <span className="muted">no run</span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
