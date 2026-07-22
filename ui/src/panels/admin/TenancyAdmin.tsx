import { useState } from "react";

import { ByChat } from "@/panels/uxFlow";
import { InvitationsCard } from "./tenancy/Invitations";
import { AiKeysCard } from "./tenancy/AiKeys";
import { OrgSettingsCard } from "./tenancy/OrgSettings";
import { UserDirectoryCard } from "./tenancy/UserDirectory";
import { WorkspacesCard } from "./tenancy/Workspaces";

type OrganisationTask = "members" | "policy" | "invitations" | "workspaces" | "ai-keys";

const ORGANISATION_TASKS: ReadonlyArray<{ id: OrganisationTask; label: string }> = [
  { id: "members", label: "Members" },
  { id: "policy", label: "Policy" },
  { id: "invitations", label: "Invitations" },
  { id: "workspaces", label: "Workspaces" },
  { id: "ai-keys", label: "AI keys" },
];

const CHAT_PHRASE: Record<OrganisationTask, string> = {
  members: "Help me review and update organisation members and their scope.",
  policy: "Help me review and update organisation policy.",
  invitations: "Help me invite a member with the right role and workspace scope.",
  workspaces: "Help me manage organisation workspaces and membership.",
  "ai-keys": "Help me manage an AI provider key reference without exposing the secret.",
};

export function TenancyAdmin() {
  const [task, setTask] = useState<OrganisationTask>("members");

  return (
    <div className="stack">
      <p className="notice">
        The one home for organisation administration: members and their scope,
        invitations, org policy, workspaces, and AI keys. Every action is governed
        server-side - one you are not permitted to take is refused with a reason,
        never silently.
      </p>

      <div className="organisation-taskbar">
        <nav className="subtabs" aria-label="Organisation tasks" role="tablist">
          {ORGANISATION_TASKS.map((item) => (
            <button
              key={item.id}
              type="button"
              id={`organisation-tab-${item.id}`}
              role="tab"
              aria-selected={task === item.id}
              aria-controls={`organisation-panel-${item.id}`}
              className={`subtab ${task === item.id ? "subtab--active" : ""}`}
              onClick={() => setTask(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <ByChat phrase={CHAT_PHRASE[task]} />
      </div>

      <div id="organisation-panel-members" role="tabpanel" aria-labelledby="organisation-tab-members" hidden={task !== "members"}>
        <UserDirectoryCard />
      </div>
      <div id="organisation-panel-policy" role="tabpanel" aria-labelledby="organisation-tab-policy" hidden={task !== "policy"}>
        <OrgSettingsCard />
      </div>
      <div id="organisation-panel-invitations" role="tabpanel" aria-labelledby="organisation-tab-invitations" hidden={task !== "invitations"}>
        <InvitationsCard />
      </div>
      <div id="organisation-panel-workspaces" role="tabpanel" aria-labelledby="organisation-tab-workspaces" hidden={task !== "workspaces"}>
        <WorkspacesCard />
      </div>
      <div id="organisation-panel-ai-keys" role="tabpanel" aria-labelledby="organisation-tab-ai-keys" hidden={task !== "ai-keys"}>
        <AiKeysCard />
      </div>
    </div>
  );
}
