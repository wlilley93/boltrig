import { useMemo, useState } from "react";

import { api } from "@/api/client";
import { useFetch } from "@/useFetch";
import { Field, InfoCallout, Select } from "@/panels/ux";
import { CardSelect, ChipPicker, SegmentedV2, Stepper } from "@/panels/uxForm";
import { ByChat, PendingHumanCard, useControlMutation } from "@/panels/uxFlow";
import { buildSkillOptions } from "@/panels/agentSlide/types";
import { runtimeOptions, type AgentModel } from "@/panels/agents/model";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}$/;

export function nextAgentName(existing: ReadonlyArray<{ name: string }>): string {
  const names = new Set(existing.map((agent) => agent.name));
  let suffix = 1;
  while (names.has(`worker-${suffix}`)) suffix += 1;
  return `worker-${suffix}`;
}

export function AgentCreateCard({
  existing,
  onCancel,
  onCreated,
}: {
  existing: AgentModel[];
  onCancel: () => void;
  onCreated: (name: string) => void;
}) {
  const skills = useFetch(() => api.skills(), []);
  const [name, setName] = useState(() => nextAgentName(existing));
  const runtimes = useMemo(() => runtimeOptions(existing), [existing]);
  const [runtime, setRuntime] = useState(() => runtimes[0] ?? "pi");
  const [supportedSkills, setSupportedSkills] = useState<string[]>(["*"]);
  const [maxDepth, setMaxDepth] = useState(2);
  const [ephemeral, setEphemeral] = useState(true);
  const [costTier, setCostTier] = useState("standard");
  const duplicate = existing.some((agent) => agent.name === name.trim());
  const validName = NAME_PATTERN.test(name.trim()) && !duplicate;
  const mutation = useControlMutation({
    verb: "control.capability.upsert",
    onApplied(_output, params) {
      onCreated(String(params.name));
    },
  });

  const params = {
    name: name.trim(),
    runtime,
    supported_skills: supportedSkills,
    max_depth: maxDepth,
    is_ephemeral: ephemeral,
    cost_tier: costTier,
  };

  return (
    <section className="form ag-create" aria-labelledby="agent-create-title">
      <h2 className="form__title" id="agent-create-title">Create agent profile</h2>
      <p className="muted">
        This profile becomes available to the live capability selector after its
        governed change is approved and applied.
      </p>

      <div className="form__grid">
        <Field
          label="Profile name"
          required
          error={
            duplicate
              ? "That profile name already exists."
              : validName
                ? undefined
                : "Use 2 to 63 lowercase letters, numbers, or hyphens."
          }
        >
          <input
            className="code"
            value={name}
            aria-label="Profile name"
            onChange={(event) => setName(event.target.value.toLowerCase())}
          />
        </Field>
        <Field label="Runtime" hint="The engine that runs this profile.">
          <Select
            value={runtime}
            ariaLabel="Agent runtime"
            onChange={setRuntime}
            options={runtimes.map((value) => ({ value, label: value }))}
          />
        </Field>
        <Field label="Max depth" hint="How many levels of sub-agents this profile may spawn.">
          <Stepper
            value={maxDepth}
            min={1}
            max={5}
            unit="levels"
            ariaLabel="Agent max depth"
            onChange={setMaxDepth}
          />
        </Field>
        <Field label="Ephemeral" hint="Ephemeral profiles are selected per task and discarded after the run.">
          <SegmentedV2
            value={ephemeral ? "yes" : "no"}
            ariaLabel="Ephemeral profile"
            onChange={(value) => setEphemeral(value === "yes")}
            options={[
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]}
          />
        </Field>
      </div>

      <Field label="Skills" hint="Choose exact skills or path patterns. All skills is the safe authoring default.">
        <ChipPicker
          value={supportedSkills}
          onChange={setSupportedSkills}
          options={buildSkillOptions(skills.data?.skills ?? [])}
          allowFree
          mono
          ariaLabel="Agent skill patterns"
          placeholder="Search skills or add a pattern"
        />
      </Field>

      <Field label="Cost tier" hint="Used by routing and budget policy.">
        <CardSelect
          value={costTier}
          onChange={setCostTier}
          options={[
            { value: "cheap", label: "Cheap", body: "Lowest-cost bulk work" },
            { value: "standard", label: "Standard", body: "Default balance" },
            { value: "premium", label: "Premium", body: "Strongest model lane" },
          ]}
        />
      </Field>

      <InfoCallout tone="consequence">
        This is a high-consequence change. It will pause for a human approval
        before it takes effect.
      </InfoCallout>

      {mutation.pending && (
        <PendingHumanCard
          hitlRequestId={mutation.pending.id}
          noun="control"
          verb="control.capability.upsert"
          sentParams={mutation.pending.params}
          onApplied={mutation.onPendingApplied}
          onDenied={mutation.onPendingDenied}
          onReset={mutation.resetPending}
        />
      )}

      <div className="form__actions">
        <button
          type="button"
          className="btn btn--primary"
          disabled={!validName || supportedSkills.length === 0 || mutation.busy || mutation.pending !== null}
          onClick={() => void mutation.invoke(params)}
        >
          {mutation.busy ? "Requesting..." : "Request agent creation"}
        </button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        <ByChat
          phrase={`Create ${ephemeral ? "an ephemeral" : "a durable"} agent profile named ${name.trim()} on ${runtime} with ${supportedSkills.join(", ")} skills.`}
        />
        {mutation.error && <span className="error">{mutation.error}</span>}
      </div>
    </section>
  );
}
