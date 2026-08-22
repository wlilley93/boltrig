import { useEffect, useState } from "react";

import type {
  IntegrationConnectionLevel,
  IntegrationManualSecretContract,
  IntegrationSecretFieldContract,
  IntegrationSecretSubmission,
} from "@wlilley93/boltrig-web-sdk";

/**
 * The connect form, extracted out of IntegrationsView so the scope picker had
 * somewhere to live.
 *
 * The extraction is not tidiness. IntegrationsView.tsx carries a structural-debt
 * entry pinned at an exact line count AND the worker gate re-loads that baseline
 * from Git and refuses any growth, so a re-pin cannot authorise adding to it --
 * the file may only stay the same or shrink. Moving this component here shrinks
 * it, and the picker costs the view one import.
 *
 * The scope choice is always offered rather than hidden behind the org policy,
 * because the client is not told that policy and guessing it would mean either
 * a second request before the form renders or a silently missing option. The
 * kernel refuses a personal connection an org has not allowed, before anything
 * is sealed, and that refusal is what the caller sees.
 */
export function ManualSecretSetup({
  contract,
  defaultLabel,
  busy,
  onSubmit,
}: {
  contract: IntegrationManualSecretContract;
  defaultLabel: string;
  busy: boolean;
  onSubmit(submission: IntegrationSecretSubmission): Promise<boolean>;
}) {
  const blank = () => Object.fromEntries(contract.fields.map((field) => [field.name, ""]));
  const [label, setLabel] = useState(defaultLabel);
  const [level, setLevel] = useState<IntegrationConnectionLevel>("org");
  const [fields, setFields] = useState<Record<string, string>>(blank);

  useEffect(() => {
    setLabel(defaultLabel);
    setLevel("org");
    setFields(blank());
  }, [contract.version, defaultLabel]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    const submitted = { ...fields };
    setFields(blank());
    await onSubmit({
      fields: submitted,
      level,
      ...(label.trim() ? { label: label.trim() } : {}),
    });
    for (const name of Object.keys(submitted)) submitted[name] = "";
  }

  return (
    <form
      className="plugins-secret-form"
      aria-label={`Connect ${defaultLabel}`}
      onSubmit={(event) => void submit(event)}
    >
      <p className="plugins-guard">
        Contract <code>{contract.version}</code> accepts only the fields below.
        Secret values are sealed once and never shown again.
      </p>
      <ScopeChoice level={level} busy={busy} onChange={setLevel} />
      <label>
        <span>Connection label</span>
        <input
          value={label}
          maxLength={200}
          required
          disabled={busy}
          onChange={(event) => setLabel(event.target.value)}
        />
      </label>
      {contract.fields.map((field) => (
        <SecretField
          key={field.name}
          field={field}
          value={fields[field.name] ?? ""}
          busy={busy}
          onChange={(value) => setFields((current) => ({ ...current, [field.name]: value }))}
        />
      ))}
      <button className="plugins-primary-action" disabled={busy || !label.trim()}>
        {busy ? "Sealing…" : "Seal and connect"}
      </button>
    </form>
  );
}

function ScopeChoice({
  level,
  busy,
  onChange,
}: {
  level: IntegrationConnectionLevel;
  busy: boolean;
  onChange(level: IntegrationConnectionLevel): void;
}) {
  return (
    <fieldset className="plugins-scope-choice">
      <legend>Whose credential is this?</legend>
      {SCOPES.map((scope) => (
        <label key={scope.value}>
          <input
            type="radio"
            name="integration-scope"
            value={scope.value}
            checked={level === scope.value}
            disabled={busy}
            onChange={() => onChange(scope.value)}
          />
          <span>{scope.label}</span>
          <small>{scope.hint}</small>
        </label>
      ))}
    </fieldset>
  );
}

function SecretField({
  field,
  value,
  busy,
  onChange,
}: {
  field: IntegrationSecretFieldContract;
  value: string;
  busy: boolean;
  onChange(value: string): void;
}) {
  return (
    <label>
      <span>{field.label}</span>
      <input
        type={field.secret ? "password" : "text"}
        autoComplete="off"
        value={value}
        minLength={field.min_length}
        maxLength={field.max_length}
        required={field.required}
        disabled={busy}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

const SCOPES: {
  value: IntegrationConnectionLevel;
  label: string;
  hint: string;
}[] = [
  {
    value: "org",
    label: "The organisation's",
    hint: "Shared. Everyone falls back to this one.",
  },
  {
    value: "user",
    label: "Just mine",
    hint: "Used for your own calls only, and the organisation has to allow it.",
  },
];
