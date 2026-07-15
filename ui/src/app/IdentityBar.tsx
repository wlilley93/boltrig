import { useIdentity, resetIdentity, updateIdentity } from "@/identity";
import { Field, InfoCallout, ROLE_OPTIONS, Select } from "@/panels/ux";
import { ChipPicker } from "@/panels/uxForm";

const GRANT_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Admin (everything)", value: "*" },
  { label: "Support agent", value: "ticket.*, conversation.*" },
  { label: "Read-only", value: "*.read" },
];

function tokens(value: string): string[] {
  return [...new Set(value.split(",").map((part) => part.trim()).filter(Boolean))];
}

function joined(values: string[]): string {
  return values.join(",");
}

function IdentityBarFields() {
  const id = useIdentity();
  return (
    <div className="identity-bar__fields">
      <Field label="Organisation" htmlFor="identity-tenant" hint="Tenant id. Use default for local development.">
        <input id="identity-tenant" value={id.tenant} onChange={(event) => updateIdentity({ tenant: event.target.value })} />
      </Field>
      <Field label="Acting as" htmlFor="identity-subject" hint="The development subject placed on the principal." example="alice">
        <input id="identity-subject" value={id.subject} onChange={(event) => updateIdentity({ subject: event.target.value })} />
      </Field>
      <Field label="Role" htmlFor="identity-role" hint="Changes cosmetic navigation and the server-side development role.">
        <Select id="identity-role" value={id.role} onChange={(role) => updateIdentity({ role })} options={ROLE_OPTIONS} />
      </Field>
      <Field label="Actor tier" htmlFor="identity-tier" hint="Simulates a human, permanent agent, or ephemeral subagent caller.">
        <Select
          id="identity-tier"
          value={id.actorTier}
          onChange={(actorTier) => updateIdentity({ actorTier: actorTier as typeof id.actorTier })}
          options={[
            { value: "human", label: "Human" },
            { value: "tier1", label: "Tier 1 agent" },
            { value: "tier2", label: "Tier 2 agent" },
            { value: "ephemeral", label: "Ephemeral subagent" },
          ]}
        />
      </Field>
      <Field label="On behalf of" htmlFor="identity-obo" hint="Optional delegated subject. Leave empty for a direct caller.">
        <input id="identity-obo" value={id.onBehalfOf} placeholder="alice" onChange={(event) => updateIdentity({ onBehalfOf: event.target.value })} />
      </Field>
      <Field label="Departments" hint="Narrows scoped work, runs, cost, and audit visibility." wide>
        <ChipPicker
          value={tokens(id.departments)}
          onChange={(values) => updateIdentity({ departments: joined(values) })}
          allowFree
          mono
          ariaLabel="Development departments"
          placeholder="Add a department"
        />
      </Field>
      <Field label="Explicit grants" hint="Grant patterns override role-derived grants in development. Leave empty to test role and verb scope." wide>
        <ChipPicker
          value={tokens(id.grants)}
          onChange={(values) => updateIdentity({ grants: joined(values) })}
          allowFree
          mono
          ariaLabel="Development grants"
          placeholder="Add noun.verb or noun.*"
        />
      </Field>
      <Field label="Role-scope verbs" hint="Used to derive grants when explicit grants are empty and the role is not org-admin." wide>
        <ChipPicker
          value={tokens(id.verbs)}
          onChange={(values) => updateIdentity({ verbs: joined(values) })}
          allowFree
          mono
          ariaLabel="Development role-scope verbs"
          placeholder="Add a scoped verb"
        />
      </Field>
    </div>
  );
}

function IdentityBarPresets() {
  return (
    <div className="identity-bar__presets">
      <span className="ux-hint">Quick grant presets:</span>
      {GRANT_PRESETS.map((preset) => (
        <button
          key={preset.label}
          type="button"
          className="tag tag--accent identity-bar__preset"
          title={`Set grants to ${preset.value}`}
          onClick={() => updateIdentity({ grants: preset.value })}
        >
          {preset.label}
        </button>
      ))}
      <button className="btn btn--ghost btn--sm" onClick={() => resetIdentity()}>
        Reset to defaults
      </button>
    </div>
  );
}

export function IdentityBar() {
  return (
    <div className="identity-bar" role="group" aria-label="Dev identity">
      <InfoCallout title="Development identity">
        These controls become <code>x-boltrig-*</code> headers only under the development resolver.
        Production derives identity, tier, delegation, scope, and grants from SSO, sessions, or personal access tokens.
      </InfoCallout>
      <IdentityBarFields />
      <IdentityBarPresets />
    </div>
  );
}
