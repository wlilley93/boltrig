import { useState } from "react";

import type { CapabilitiesResponse, VerbInfo } from "@/api/types";
import type { FetchState } from "@/useFetch";

interface VerbPaletteProps {
  caps: FetchState<CapabilitiesResponse>;
}

export function VerbPalette({ caps }: VerbPaletteProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const verbs: VerbInfo[] = caps.data?.verbs ?? [];

  async function copyVerb(verbId: string) {
    try {
      await navigator.clipboard.writeText(verbId);
      setCopiedId(verbId);
    } catch {
      // Clipboard may be unavailable (insecure context); fail quietly.
    }
  }

  return (
    <div className="list-card">
      <div className="list-card__head">
        <h3>Verb palette</h3>
        <button className="btn" onClick={() => caps.reload()}>
          Refresh
        </button>
      </div>
      <div className="list-card__body">
        <p className="muted">
          Scoped to this identity. Click a verb to copy its id, then paste it
          as a step <code>action</code> in the definition JSON.
        </p>
        {caps.loading && !caps.data && <p className="muted">Loading...</p>}
        {caps.error && <p className="error">Failed to load: {caps.error}</p>}
        {!caps.loading && !caps.error && verbs.length === 0 && (
          <p className="muted">No verbs visible for this identity.</p>
        )}
        {verbs.map((v) => (
          <button
            className="row-line palette-row"
            key={v.id}
            onClick={() => copyVerb(v.id)}
            title="Copy verb id"
          >
            <div>
              <code>{v.id}</code>{" "}
              {v.consequence && <span className="muted">({v.consequence})</span>}
            </div>
            <div className="kv">
              {v.binding && <span className="badge">{v.binding.target_type}</span>}
              <span className="muted">{copiedId === v.id ? "copied" : "copy"}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
