// Shared pieces for the settings slides (Beat 5 chunk 1: SettingsPanel.tsx
// split into one slide per section). Only helpers used by MORE than one slide
// live here; single-section helpers moved with their slide.

import { useState } from "react";

import { api } from "../../api/client";
import type { PatView } from "../../api/types";
import { useFetch } from "../../useFetch";
import { GrantList, errText } from "../shared";

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
  const [error, setError] = useState<string | null>(null);

  async function revoke(id: string) {
    if (
      !window.confirm(
        "Revoke this token? Any client using it stops working immediately.",
      )
    ) {
      return;
    }
    setError(null);
    try {
      const res = await api.revokeToken(id);
      if (res.status === "ok") tokens.reload();
      else setError(res.reason ?? "revoke rejected");
    } catch (err) {
      setError(errText(err));
    }
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
        {tokens.loading && !tokens.data && <p className="muted">Loading...</p>}
        {tokens.error && (
          <p className="error">Failed to load: {tokens.error}</p>
        )}
        {error && <p className="error">{error}</p>}
        {!tokens.loading && list.length === 0 && (
          <p className="muted">No tokens yet.</p>
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
              <button className="btn" onClick={() => void revoke(t.id)}>
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
