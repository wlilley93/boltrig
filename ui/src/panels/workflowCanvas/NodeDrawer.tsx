// Left-side node drawer (design brief sec 22.5). Slides in over a blurred
// backdrop when the dock Plus button is pressed. A search bar filters items by
// name; the four categories list their items (28px icon square, name, desc).
// Items are draggable onto the canvas (cursor:grab) or click-to-add at centre.

import { useMemo, useState } from "react";
import { CATEGORIES, type NodeKindMeta, type NodeVisualKind } from "./nodeTaxonomy";
import { NodeIcon } from "./nodeIcons";

export const DRAWER_DRAG_KIND = "application/x-boltrig-node-kind";

interface NodeDrawerProps {
  open: boolean;
  onAdd: (kind: NodeVisualKind) => void;
  onClose: () => void;
}

export function NodeDrawer({ open, onAdd, onClose }: NodeDrawerProps) {
  const [query, setQuery] = useState("");

  const categories = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return CATEGORIES;
    return CATEGORIES.map((c) => ({
      ...c,
      items: c.items.filter(
        (i) => i.name.toLowerCase().includes(q) || i.desc.toLowerCase().includes(q),
      ),
    })).filter((c) => c.items.length > 0);
  }, [query]);

  return (
    <>
      <div
        className={`wf3-drawer-backdrop ${open ? "is-open" : ""}`}
        onClick={onClose}
        aria-hidden={!open}
      />
      <aside
        className={`wf3-drawer ${open ? "is-open" : ""}`}
        aria-hidden={!open}
        aria-label="Node library"
      >
        <div className="wf3-drawer__search">
          <input
            type="search"
            placeholder="Search nodes"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="Search nodes"
          />
        </div>
        <div className="wf3-drawer__scroll">
          {categories.length === 0 && <p className="wf3-drawer__empty muted">No matches.</p>}
          {categories.map((cat) => (
            <section className="wf3-drawer__cat" key={cat.id}>
              <h3 className="wf3-drawer__cat-title">{cat.label}</h3>
              {cat.items.map((item) => (
                <DrawerItem key={item.kind} item={item} onAdd={onAdd} />
              ))}
            </section>
          ))}
        </div>
      </aside>
    </>
  );
}

function DrawerItem({
  item,
  onAdd,
}: {
  item: NodeKindMeta;
  onAdd: (kind: NodeVisualKind) => void;
}) {
  return (
    <button
      type="button"
      className="wf3-drawer__item"
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DRAWER_DRAG_KIND, item.kind);
        e.dataTransfer.effectAllowed = "move";
      }}
      onClick={() => onAdd(item.kind)}
      title={`Add ${item.name}`}
    >
      <span
        className="wf3-drawer__item-icon"
        style={{ background: "rgba(255,255,255,0.05)", color: item.color }}
      >
        <NodeIcon name={item.icon} size={18} />
      </span>
      <span className="wf3-drawer__item-text">
        <span className="wf3-drawer__item-name">{item.name}</span>
        <span className="wf3-drawer__item-desc muted">{item.desc}</span>
      </span>
    </button>
  );
}
