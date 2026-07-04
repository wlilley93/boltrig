/** GrantList: mono chips for grant/scope patterns, expandable beyond 8.
 * Supersedes the fixed renderer in shared.tsx for long lists (PAT scopes,
 * skill tool_grants); import from here when the list can exceed the cap.
 */

import { useState } from "react";

export function GrantList({
  grants,
  limit,
}: {
  grants?: string[];
  limit?: number; // chips shown before "+n more"; default 8
}) {
  const [expanded, setExpanded] = useState(false);
  const max = limit ?? 8;
  if (!grants || grants.length === 0) {
    return <span className="muted">none</span>;
  }
  const shown = expanded ? grants : grants.slice(0, max);
  const hidden = grants.length - shown.length;
  return (
    <span className="ux-grants">
      {shown.map((g, i) => (
        <code className="tag" key={`${g}-${i}`}>
          {g}
        </code>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          onClick={() => setExpanded(true)}
        >
          +{hidden} more
        </button>
      )}
      {expanded && grants.length > max && (
        <button
          type="button"
          className="btn btn--sm btn--ghost"
          onClick={() => setExpanded(false)}
        >
          show fewer
        </button>
      )}
    </span>
  );
}
