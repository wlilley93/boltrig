import type { AuditTreeResponse } from "@/api/types";
import { isNotFound } from "./utils";

export function RunRaw({
  tree,
  loading,
  error,
}: {
  tree: AuditTreeResponse | null;
  loading: boolean;
  error: string | null;
}) {
  return (
    <div className="run-raw">
      <h4>Raw audit tree</h4>
      {loading && !tree && <p className="muted">Loading audit tree...</p>}
      {error && isNotFound(error) && (
        <p className="notice warn">Audit tree not found, or not in your visibility scope.</p>
      )}
      {error && !isNotFound(error) && <p className="error">Audit tree: {error}</p>}
      {!loading && !tree && !error && <p className="muted">No audit tree is available yet.</p>}
      {tree && <pre className="codeblock run-raw__json">{JSON.stringify(tree, null, 2)}</pre>}
    </div>
  );
}
