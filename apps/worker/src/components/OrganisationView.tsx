import { useEffect, useState } from "react";
import type {
  OrganisationView as Organisation,
  UserProfile,
} from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { Topbar, Unavailable } from "./Shell";
import {
  AdminDirectory,
  InvitationAdministration,
  OrganisationRoster,
} from "./OrganisationDirectorySections";
import {
  OrganisationPolicy,
  WorkspaceAdministration,
} from "./OrganisationWorkspaceSections";

type OrganisationTab = "overview" | "workspaces" | "administration";

export function OrganisationView() {
  const [organisation, setOrganisation] = useState<Organisation | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [tab, setTab] = useState<OrganisationTab>("overview");
  const [error, setError] = useState("");

  function refresh() {
    setError("");
    void Promise.all([client.currentOrg(), client.meSettings()])
      .then(([orgResult, meResult]) => {
        setOrganisation(orgResult.organisation);
        setProfile(meResult.profile);
      })
      .catch(() => setError("Organisation administration is unavailable."));
  }

  useEffect(refresh, []);

  const canAdmin = Boolean(profile && adminRoles.has(profile.role ?? ""));

  return (
    <div className="page">
      <Topbar title="Organisation" status={organisation?.name ?? "Loading"} />
      <div className="page-content">
        <div className="page-intro">
          <div>
            <h2>Organisation and workspaces</h2>
            <p>Membership, policy and administration remain enforced by canonical server roles.</p>
          </div>
        </div>
        <nav className="tabs" aria-label="Organisation sections">
          {([
            ["overview", "Overview"],
            ["workspaces", "Workspaces"],
            ["administration", "Administration"],
          ] as const).map(([id, label]) => (
            <button
              className={tab === id ? "active" : ""}
              key={id}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        {error && <Unavailable title="Organisation unavailable">{error}</Unavailable>}
        {!error && (!organisation || !profile) && <p className="muted">Loading organisation…</p>}
        {organisation && profile && tab === "overview" && (
          <div className="settings-grid">
            <OrganisationPolicy
              organisation={organisation}
              canAdmin={canAdmin}
              onChanged={refresh}
            />
            <OrganisationRoster />
          </div>
        )}
        {organisation && profile && tab === "workspaces" && (
          <div className="settings-grid">
            <WorkspaceAdministration currentUser={profile.id} canAdmin={canAdmin} />
          </div>
        )}
        {organisation && profile && tab === "administration" && (
          canAdmin ? (
            <div className="settings-grid">
              <AdminDirectory currentRole={profile.role ?? "member"} />
              <InvitationAdministration currentRole={profile.role ?? "member"} />
            </div>
          ) : (
            <Unavailable title="Administration restricted">
              Your current server role does not permit organisation administration.
            </Unavailable>
          )
        )}
      </div>
    </div>
  );
}

const adminRoles = new Set(["superadmin", "admin", "org-admin"]);
