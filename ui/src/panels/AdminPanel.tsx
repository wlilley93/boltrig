// The admin console (Epic ADM, Beat 5 retrofit). The manifest stays the source
// of truth: this surface edits a section through TYPED controls (SchemaFormV2 +
// the form register), never a raw JSON blob. Two rails changed from the round
// three console:
//   1. Every WRITE goes through the governed control.config.upsert verb (the
//      same request-change/approval path Agents and Automations use): the first
//      submit 202s, a DiffView shows old vs new, and a PendingHumanCard applies
//      the change on approval. Direct config PUT is no longer used here.
//   2. Fail-closed validation: an unparseable per-field JSON escape hatch blocks
//      Save (SchemaFormV2.onValidity), and a section schema is an allowlist so a
//      partial edit preserves operator-only keys (e.g. OIDC wiring) untouched.
// Reads (revision history, manifest export, credential references) are
// unchanged; rollback now uses in-frame ArmConfirm instead of window.confirm.
// The server gates writes to author/admin roles; a 403 renders as a denial.
//
// This file is a thin orchestrator: the state and data hooks live in admin/
// (useAdminPanel composes useAdminConfig + useAdminSidebars) and the
// configuration view renders through AdminConfigView, so every file stays under
// the structural floor.

import { ADMIN_SECTION_OPTIONS } from "./admin/sections";
import { AdminConfigView } from "./admin/AdminConfigView";
import { ADMIN_VIEWS } from "./admin/adminConstants";
import { TenancyAdmin } from "./admin/TenancyAdmin";
import { useAdminPanel } from "./admin/useAdminPanel";
import { PageIntro, Select } from "./ux";
import { SegmentedV2 } from "./uxForm";

export function AdminPanel() {
  const a = useAdminPanel();

  return (
    <section className="panel">
      <PageIntro
        title="Admin"
        lead="Configuration and organisation administration, through typed, governed controls."
        howToggle
        how="Configuration edits a manifest section and requests a governed change - a high-consequence amendment pauses for a human approval, then records a revision you can roll back to. Organisation administers members, invitations, workspaces and AI keys. Secrets are never shown, only referenced."
        actions={
          a.view === "config" ? (
            <>
              <div style={{ minWidth: 200 }}>
                <Select
                  value={a.sectionKey}
                  ariaLabel="Manifest section"
                  onChange={a.setSectionKey}
                  options={ADMIN_SECTION_OPTIONS}
                />
              </div>
              <button className="btn" onClick={() => void a.loadSection(a.section)}>
                Reload
              </button>
            </>
          ) : undefined
        }
      />

      <div className="admin__viewtoggle">
        <SegmentedV2
          value={a.view}
          onChange={a.setView}
          options={ADMIN_VIEWS}
          ariaLabel="Admin console view"
        />
      </div>

      {!a.isAdmin && (
        <p className="notice warn">
          The admin console is intended for org-admin. This identity (role:{" "}
          <code>{a.identity.role}</code>) may be rejected by the server with 403.
        </p>
      )}

      {a.view === "organisation" && <TenancyAdmin />}

      {a.view === "config" && <AdminConfigView a={a} />}
    </section>
  );
}
