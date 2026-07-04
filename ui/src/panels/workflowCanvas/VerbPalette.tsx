import type { VerbInfo } from "@/api/types";
import { deriveKind } from "./graph";

interface VerbPaletteProps {
  verbs: VerbInfo[];
  filter: string;
  onFilter: (v: string) => void;
  onAdd: (verb: VerbInfo) => void;
}

export function VerbPalette({ verbs, filter, onFilter, onAdd }: VerbPaletteProps) {
  return (
    <div className="form">
      <div className="form__title">Verb palette</div>
      <p className="muted">
        Scoped to this identity. Click a verb to drop a step node; its kind is
        derived from the verb binding. Drag handle to handle to add a parent link.
      </p>
      {verbs.length > 6 && (
        <input
          className="wf-palette__search"
          placeholder="Search actions..."
          value={filter}
          onChange={(e) => onFilter(e.target.value)}
          aria-label="Search actions"
        />
      )}
      <div className="wf-palette">
        {verbs
          .filter((v) => {
            const q = filter.trim().toLowerCase();
            return (
              !q ||
              v.id.toLowerCase().includes(q) ||
              v.noun.toLowerCase().includes(q)
            );
          })
          .map((v) => (
            <button
              className="row-line palette-row"
              key={v.id}
              onClick={() => onAdd(v)}
              title="Add as a step node"
            >
              <div className="kv">
                <code>{v.id}</code>
                {v.consequence === "high" && (
                  <span className="badge badge--conseq-high">high</span>
                )}
              </div>
              <span className="badge">{deriveKind(v)}</span>
            </button>
          ))}
      </div>
    </div>
  );
}
