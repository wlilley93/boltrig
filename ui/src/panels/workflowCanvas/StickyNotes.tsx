// Canvas sticky notes (design brief sec 22.10). Amber-tinted, absolutely
// positioned, draggable annotations. Ephemeral: kept in canvas state only (not
// persisted to the workflow definition yet). A small "+" adds a blank note.

import { useState } from "react";

export interface StickyNote {
  id: string;
  x: number;
  y: number;
  text: string;
}

interface StickyNotesProps {
  notes: StickyNote[];
  onChange: (notes: StickyNote[]) => void;
}

export function StickyNotes({ notes, onChange }: StickyNotesProps) {
  const [editing, setEditing] = useState<string | null>(null);

  const addNote = () => {
    const id = `note_${Date.now()}`;
    onChange([
      ...notes,
      { id, x: 120 + (notes.length % 5) * 24, y: 120 + (notes.length % 5) * 24, text: "" },
    ]);
    setEditing(id);
  };

  const update = (id: string, patch: Partial<StickyNote>) =>
    onChange(notes.map((n) => (n.id === id ? { ...n, ...patch } : n)));

  const remove = (id: string) => onChange(notes.filter((n) => n.id !== id));

  return (
    <div className="wf3-notes">
      <button
        type="button"
        className="wf3-notes__add"
        onClick={addNote}
        title="Add sticky note"
        aria-label="Add sticky note"
      >
        +
      </button>
      {notes.map((n) => (
        <StickyNoteCard
          key={n.id}
          note={n}
          editing={editing === n.id}
          onFocus={() => setEditing(n.id)}
          onBlur={() => setEditing(null)}
          onChange={(patch) => update(n.id, patch)}
          onRemove={() => remove(n.id)}
        />
      ))}
    </div>
  );
}

interface NoteProps {
  note: StickyNote;
  editing: boolean;
  onFocus: () => void;
  onBlur: () => void;
  onChange: (patch: Partial<StickyNote>) => void;
  onRemove: () => void;
}

function StickyNoteCard({
  note,
  editing,
  onFocus,
  onBlur,
  onChange,
  onRemove,
}: NoteProps) {
  const onDragStart = (e: React.MouseEvent) => {
    const startX = e.clientX;
    const startY = e.clientY;
    const origX = note.x;
    const origY = note.y;
    const onMove = (ev: MouseEvent) => {
      onChange({ x: origX + (ev.clientX - startX), y: origY + (ev.clientY - startY) });
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    e.stopPropagation();
  };

  return (
    <div
      className="wf3-note"
      style={{ left: note.x, top: note.y }}
      onMouseDown={onDragStart}
    >
      <button
        type="button"
        className="wf3-note__close"
        onClick={onRemove}
        aria-label="Delete note"
        title="Delete note"
      >
        x
      </button>
      <textarea
        className="wf3-note__text"
        value={note.text}
        placeholder="Note..."
        onFocus={onFocus}
        onBlur={onBlur}
        onChange={(e) => onChange({ text: e.target.value })}
        data-editing={editing}
      />
    </div>
  );
}
