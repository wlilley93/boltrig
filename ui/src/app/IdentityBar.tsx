import { useIdentity, resetIdentity, updateIdentity } from "@/identity";
import { Field, InfoCallout, ROLE_OPTIONS, Select } from "@/panels/ux";

const GRANT_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: "Admin (everything)", value: "*" },
  { label: "Support agent", value: "ticket.*, conversation.*" },
  { label: "Read-only", value: "*.read" },
];

function IdentityBarFields() {
  const id = useIdentity();
  return (
    <div className="identity-bar__fields">
      <Field
        label="Organisation"
        hint="Your organisation (tenant) id. Use 'default' for local dev."
      >
        <input
          value={id.tenant}
          onChange={(e) => updateIdentity({ tenant: e.target.value })}
        />
      </Field>

      <Field
        label="Acting as"
        hint="The user id you are acting as - anything works in dev."
        example="alice"
      >
        <input
          value={id.subject}
          onChange={(e) => updateIdentity({ subject: e.target.value })}
        />
      </Field>

      <Field
        label="Role"
        hint="Controls which tabs you see and what the server lets you do. org-admin sees everything; agent is the most limited."
      >
        <Select
          value={id.role}
          ariaLabel="Role"
          onChange={(v) => updateIdentity({ role: v })}
          options={ROLE_OPTIONS}
        />
      </Field>

      <Field
        label="Departments"
        hint="Comma-separated departments you belong to. Narrows what you see in Insight, runs and audit. Leave blank for no extra restriction."
        example="support, billing"
        wide
      >
        <input
          value={id.departments}
          placeholder="support, billing"
          onChange={(e) => updateIdentity({ departments: e.target.value })}
        />
      </Field>

      <Field
        label="Grants"
        hint="What this identity is allowed to do. A grant is a verb id or pattern: * is everything, ticket.* is all ticket actions, ticket.create is one action."
        wide
      >
        <input
          value={id.grants}
          placeholder="* or ticket.*, conversation.read"
          onChange={(e) => updateIdentity({ grants: e.target.value })}
        />
      </Field>
    </div>
  );
}

function IdentityBarPresets() {
  return (
    <div className="identity-bar__presets">
      <span className="ux-hint">Quick presets:</span>
      {GRANT_PRESETS.map((p) => (
        <button
          key={p.label}
          type="button"
          className="tag tag--accent identity-bar__preset"
          title={`Set grants to ${p.value}`}
          onClick={() => updateIdentity({ grants: p.value })}
        >
          {p.label}
        </button>
      ))}
      <button
        className="btn btn--ghost btn--sm"
        title="Restore the default dev identity (org 'default', acting as 'dev', role org-admin, grants *)"
        onClick={() => resetIdentity()}
      >
        Reset to defaults
      </button>
    </div>
  );
}

export function IdentityBar() {
  return (
    <div className="identity-bar" role="group" aria-label="Dev identity">
      <InfoCallout title="Dev sign-in">
        These five values become the <code>x-boltrig-*</code> headers on every
        request, so you can act as any user while building. Production resolves
        identity from SSO or a personal access token instead - the backend
        already supports it.
      </InfoCallout>

      <IdentityBarFields />
      <IdentityBarPresets />
    </div>
  );
}
