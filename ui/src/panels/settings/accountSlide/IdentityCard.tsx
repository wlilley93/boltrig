import { FetchError } from "@/panels/ux";
import { Skeleton } from "@/panels/uxFlow";
import { scopeReadable } from "@/panels/settings/shared";

import type { AccountProfileState } from "./useAccountProfile";

export function IdentityCard({ s }: { s: AccountProfileState }) {
  const { settings } = s;
  const profile = settings.data?.profile;

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Identity</h3>
        <span className="muted">from your IdP</span>
      </div>
      <div className="list-card__body">
        {settings.loading && !settings.data && (
          <Skeleton variant="rows" count={6} />
        )}
        <FetchError
          error={settings.error}
          status={settings.errorStatus}
          onRetry={settings.reload}
        />
        {profile && (
          <>
            <div className="row-line">
              <span className="muted">id</span>
              <code>{profile.id}</code>
            </div>
            <div className="row-line">
              <span className="muted">email</span>
              <span>{profile.email ?? "-"}</span>
            </div>
            <div className="row-line">
              <span className="muted">role</span>
              <code className="tag">{profile.role ?? "-"}</code>
            </div>
            <div className="row-line">
              <span className="muted">status</span>
              <span
                className={`badge ${profile.status === "deactivated" ? "badge--down" : "badge--ok"}`}
              >
                {profile.status ?? "-"}
              </span>
            </div>
            <div className="row-line">
              <span className="muted">source IdP group</span>
              <span>{profile.source_group ?? "-"}</span>
            </div>
            <div className="row-line">
              <span className="muted">scope</span>
              <span>{scopeReadable(profile.scope)}</span>
            </div>
            <p className="muted">
              Role, scope and group are conferred by your identity provider and
              are read-only here. Change them via your IdP, or ask an org-admin.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
