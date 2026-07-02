// Shared pieces for the settings slides (Beat 5 chunk 1: SettingsPanel.tsx
// split into one slide per section). Only helpers used by MORE than one slide
// live here; single-section helpers moved with their slide.

import { api } from "../../api/client";
import type { PatView } from "../../api/types";
import { useFetch } from "../../useFetch";
import { GrantList } from "../shared";
import { EmptyState, FetchError } from "../ux";
import { ArmConfirm, Skeleton } from "../uxFlow";

// A scope dict (departments / nouns / verbs visible) rendered compactly.
// Used by the account (own profile) and organisation (directory) slides.
export function scopeReadable(scope: Record<string, unknown> | undefined): string {
  if (!scope || Object.keys(scope).length === 0) return "none";
  return Object.entries(scope)
    .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join("/") : String(v)}`)
    .join("; ");
}

// --- Personal access tokens (shared list, used by two slides) ---------------
// Rendered on the developer slide (below the mint form) and again on the
// security slide (standing credentials).

export function TokenList({ bump = 0 }: { bump?: number }) {
  const tokens = useFetch(() => api.meTokens(), [bump]);

  // Throws on a rejected revoke so the row's ArmConfirm renders the reason.
  async function revoke(id: string) {
    const res = await api.revokeToken(id);
    if (res.status !== "ok") {
      throw new Error(res.reason ?? "revoke rejected");
    }
    tokens.reload();
  }

  const list: PatView[] = tokens.data?.tokens ?? [];

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Personal access tokens</h3>
        <button className="btn" onClick={() => tokens.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        {tokens.loading && !tokens.data && <Skeleton variant="rows" />}
        <FetchError
          error={tokens.error}
          status={tokens.errorStatus}
          onRetry={tokens.reload}
        />
        {tokens.data && list.length === 0 && (
          <EmptyState
            title="No tokens yet"
            body="Mint one to connect Claude Code, curl, or any MCP client."
          />
        )}
        {list.map((t) => (
          <div className="row-line" key={t.id}>
            <div>
              <code>{t.name}</code>{" "}
              {t.revoked && <span className="badge badge--down">revoked</span>}
              <div className="muted">
                created {t.created_at ?? "-"} - last used{" "}
                {t.last_used_at ?? "never"} - expires {t.expires_at ?? "-"}
              </div>
              <GrantList grants={t.scope} />
            </div>
            {!t.revoked && (
              <ArmConfirm
                label="Revoke"
                armLabel={
                  <>
                    Revoke <code>{t.name}</code>? Any client using it stops
                    working immediately.
                  </>
                }
                confirmLabel="Confirm revoke"
                tone="danger"
                busyLabel="Revoking..."
                onConfirm={() => revoke(t.id)}
              />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
