import type { ReactNode } from "react";

import type { MemoryFactView, MemoryProvenance } from "@/api/types";
import { CodeBlock } from "@/panels/shared";

type FactCardProps = {
  fact: MemoryFactView;
  footer?: ReactNode;
};

// One fact rendered as a card: content plus the metadata (owner_scope, kind,
// data_class) and the provenance that shows how/why it is known. An optional
// footer carries per-tab controls (e.g. the Browse "Forget" button).
export function FactCard({ fact, footer }: FactCardProps) {
  const prov: MemoryProvenance = fact.provenance ?? {};
  const hasHops = typeof prov.hops === "number";
  const path = prov.path ?? [];
  return (
    <div className="mem-fact">
      <div className="mem-fact__head">
        <span className="kv">
          <code className="tag" title="The type of fact">{fact.kind}</code>
          <span
            className="badge ux-termtip"
            title="Who this fact belongs to - your user scope, a department, or the org."
          >
            {fact.owner_scope}
          </span>
          <span
            className={`badge ${
              fact.data_class === "sensitive" ? "badge--down" : "badge--ok"
            }`}
            title={
              fact.data_class === "sensitive"
                ? "Sensitive - kept on a local-only endpoint."
                : "Standard data."
            }
          >
            {fact.data_class}
          </span>
        </span>
        <code className="muted mem-fact__id">{fact.id}</code>
      </div>

      {typeof fact.content === "string" ? (
        <p className="mem-fact__text">{fact.content}</p>
      ) : (
        <CodeBlock value={fact.content} />
      )}

      <div className="mem-fact__prov">
        <span className="muted">
          via {prov.source_kind ?? "unknown"}
          {prov.source_ref ? " from " : ""}
        </span>
        {prov.source_ref && <code className="tag">{prov.source_ref}</code>}
        {prov.created_at && (
          <span className="muted">{prov.created_at}</span>
        )}
        {hasHops && (
          <span className="badge" title="How many links away this fact was reached in Connections mode.">
            {prov.hops} link(s) away
          </span>
        )}
      </div>

      {path.length > 0 && (
        <div className="mem-fact__path">
          <span className="muted">path:</span>
          <span className="kv">
            {path.map((step, i) => (
              <code className="tag" key={`${step}-${i}`}>
                {step}
              </code>
            ))}
          </span>
        </div>
      )}

      {footer && <div className="mem-fact__foot">{footer}</div>}
    </div>
  );
}
