import { useActiveContext } from "./useActiveContext";

/**
 * Switching the workspace or organisation a session is bound to.
 *
 * Extracted from AccountSecuritySections, a grab-bag of five unrelated account
 * panels sitting at a structural pin. This one is worth its own file: it is the
 * only control on the estate that changes what the WHOLE application is looking
 * at, and the reasoning for the reload it now performs needs room to be read
 * (see useActiveContext).
 */
export function ActiveContext({ onChanged }: { onChanged?(): void }) {
  const context = useActiveContext(onChanged);

  return (
    <section className="settings-card">
      <p className="eyebrow">Active context</p>
      <h2>Organisation and workspace</h2>
      <select
        className="field-control"
        aria-label="Active workspace"
        value={context.workspaceId}
        onChange={(event) => context.setWorkspaceId(event.target.value)}
      >
        {context.workspaces.map((workspace) => (
          <option value={workspace.id} key={workspace.id}>{workspace.name}</option>
        ))}
      </select>
      <button
        className="secondary-button"
        disabled={!context.workspaceId}
        onClick={() => void context.switchWorkspace()}
      >
        Switch workspace
      </button>
      <select
        className="field-control"
        aria-label="Active organisation"
        value={context.orgId}
        onChange={(event) => context.setOrgId(event.target.value)}
      >
        {context.organisations.map((organisation) => (
          <option value={organisation.id} key={organisation.id}>
            {organisation.id}{organisation.active ? " (current)" : ""}
          </option>
        ))}
      </select>
      <button
        className="secondary-button"
        disabled={!context.orgId.trim()}
        onClick={() => void context.switchOrg()}
      >
        Switch organisation
      </button>
      <p>The server re-authorises membership before changing either context.</p>
      {context.message && <p className="notice" role="status">{context.message}</p>}
    </section>
  );
}
