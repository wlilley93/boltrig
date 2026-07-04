import { InvitationsCard } from "./tenancy/Invitations";
import { AiKeysCard } from "./tenancy/AiKeys";
import { OrgSettingsCard } from "./tenancy/OrgSettings";
import { UserDirectoryCard } from "./tenancy/UserDirectory";
import { WorkspacesCard } from "./tenancy/Workspaces";

export function TenancyAdmin() {
  return (
    <div className="stack">
      <p className="notice">
        The one home for organisation administration: members and their scope,
        invitations, org policy, workspaces, and AI keys. Every action is governed
        server-side - one you are not permitted to take is refused with a reason,
        never silently.
      </p>
      <UserDirectoryCard />
      <div className="cols">
        <div className="stack">
          <OrgSettingsCard />
          <InvitationsCard />
          <AiKeysCard />
        </div>
        <WorkspacesCard />
      </div>
    </div>
  );
}
