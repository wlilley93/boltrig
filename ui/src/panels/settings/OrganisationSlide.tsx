// Settings / Organisation (org-admin): a signpost, not a second settings system.
// All organisation administration - the member directory + scope, invitations,
// org policy, workspaces, and AI keys - now lives together in the Admin console
// (panels/admin/TenancyAdmin.tsx), so there is one home for it. This slide just
// deep-links there (#/admin/organisation opens the Admin org view directly).

import { navigate } from "../../router";
import { Hint, PageIntro } from "../ux";

export function OrganisationSlide() {
  return (
    <section className="panel">
      <PageIntro
        title="Organisation"
        lead="Members, invitations, workspaces, policy and AI keys - all in one place."
      />
      <div className="form">
        <div className="form__title">Organisation administration</div>
        <Hint>
          The member directory, invitations, org policy, workspaces and AI keys
          are managed together in the Admin console, so there is a single home for
          organisation administration.
        </Hint>
        <div className="form__actions">
          <button
            className="btn btn--primary"
            onClick={() => navigate("/admin/organisation")}
          >
            Open in Admin
          </button>
        </div>
      </div>
    </section>
  );
}
