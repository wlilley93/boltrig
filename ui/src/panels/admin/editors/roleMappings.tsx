// Dedicated typed editor for identity.role_mappings - the RBAC source of truth
// (US-IAM-01/02). The generic array-of-objects path cannot express the scope,
// which is a small union ({all: true} | {departments, nouns, verbs}); a raw JSON
// blob here is exactly the #1 UX finding. Each mapping is a row-card: an IdP-group
// Field, a role Select over the canonical ROLE_OPTIONS, and a structured scope
// sub-editor. Presentational only - value in, value out via onChange, reusing the
// form register primitives (no bare inputs beyond the same free-text pattern the
// register itself uses for a plain string).

import type { FieldEditorProps } from "../../uxForm";
import { ChipPicker, Switch } from "../../uxForm";
import { Field, ROLE_OPTIONS, Select } from "../../ux";

interface RoleMapping {
  idp_group?: string;
  role?: string;
  scope?: unknown;
}

const HEADER_STYLE = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
} as const;

function asStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.map((x) => String(x)) : [];
}

// The scope union rendered as typed controls: a "full access" switch (the
// {all: true} ceiling that maps to the "*" grant), and when it is off, three
// free-entry chip lists for the department / noun / verb scoping.
function ScopeEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (v: Record<string, unknown>) => void;
}) {
  const scope = (
    value && typeof value === "object" && !Array.isArray(value) ? value : {}
  ) as Record<string, unknown>;
  const all = scope.all === true;
  const departments = asStringArray(scope.departments);
  const nouns = asStringArray(scope.nouns);
  const verbs = asStringArray(scope.verbs);
  const setKey = (k: string, v: string[]) => onChange({ ...scope, [k]: v });
  return (
    <div className="ux-inset">
      <span className="ux-inset__label">Scope</span>
      <Switch
        checked={all}
        label="Full access (every verb)"
        hint="The tenant-wide ceiling: an { all: true } scope maps to the '*' grant."
        onChange={(on) =>
          onChange(on ? { all: true } : { departments, nouns, verbs })
        }
      />
      {!all && (
        <div className="ux-inset__grid">
          <Field label="Departments" hint="Departments this role is scoped to.">
            <ChipPicker
              value={departments}
              onChange={(v) => setKey("departments", v)}
              allowFree
              ariaLabel="Departments"
            />
          </Field>
          <Field label="Nouns" hint="Resource nouns this role may act on (ticket, jira, ...).">
            <ChipPicker
              value={nouns}
              onChange={(v) => setKey("nouns", v)}
              allowFree
              ariaLabel="Nouns"
            />
          </Field>
          <Field label="Verbs" hint="Exact verbs granted (ticket.read, ticket.create, ...).">
            <ChipPicker
              value={verbs}
              onChange={(v) => setKey("verbs", v)}
              allowFree
              ariaLabel="Verbs"
            />
          </Field>
        </div>
      )}
    </div>
  );
}

export function RoleMappingList({ value, onChange, label, required, error }: FieldEditorProps) {
  const rows: RoleMapping[] = Array.isArray(value) ? (value as RoleMapping[]) : [];
  const setRow = (i: number, next: RoleMapping) => {
    const arr = rows.slice();
    arr[i] = next;
    onChange(arr);
  };
  const removeRow = (i: number) => {
    const arr = rows.slice();
    arr.splice(i, 1);
    onChange(arr);
  };
  const addRow = () => onChange([...rows, { idp_group: "", role: "agent", scope: { verbs: [] } }]);

  return (
    <div className="ux-inset ux-field--wide">
      <span className="ux-inset__label">
        {label}
        {required && (
          <em className="ux-field__req" title="required">
            {" "}
            *
          </em>
        )}
      </span>
      <span className="ux-field__hint">
        Each entry maps an IdP group to a role and a permission scope. This is the RBAC source of
        truth.
      </span>
      {error != null && (
        <span className="ux-field__error" role="alert">
          {error}
        </span>
      )}
      {rows.length === 0 && <span className="ux-field__hint">No mappings yet. Add one below.</span>}
      <div className="stack">
        {rows.map((row, i) => (
          <div key={i} className="ux-inset">
            <span className="ux-inset__label" style={HEADER_STYLE}>
              <span>Mapping {i + 1}</span>
              <button
                type="button"
                className="btn btn--sm btn--ghost"
                aria-label={`Remove mapping ${i + 1}`}
                onClick={() => removeRow(i)}
              >
                Remove
              </button>
            </span>
            <div className="ux-inset__grid">
              <Field label="IdP group" hint="The identity-provider group this rule matches.">
                <input
                  aria-label="IdP group"
                  value={row.idp_group ?? ""}
                  onChange={(e) => setRow(i, { ...row, idp_group: e.target.value })}
                />
              </Field>
              <Field label="Role" hint="The role granted to members of this group.">
                <Select
                  ariaLabel="Role"
                  value={row.role ?? ""}
                  onChange={(v) => setRow(i, { ...row, role: v })}
                  options={
                    row.role ? ROLE_OPTIONS : [{ value: "", label: "Choose..." }, ...ROLE_OPTIONS]
                  }
                />
              </Field>
            </div>
            <ScopeEditor value={row.scope} onChange={(s) => setRow(i, { ...row, scope: s })} />
          </div>
        ))}
      </div>
      <div>
        <button type="button" className="btn btn--sm" onClick={addRow}>
          Add mapping
        </button>
      </div>
    </div>
  );
}
