// Command palette (Cmd/Ctrl-K): a fast jump-to-anything overlay. Lists the
// pages and the caller's scoped verbs; selecting a page navigates, selecting a
// verb jumps to the Dev console to run it. Pure client; capabilities load lazily
// the first time it opens. Esc closes, arrow keys move, Enter runs.
//
// Thin orchestrator: state, hotkey/keyboard handling and command building live
// in commandPalette/ (useCommandPalette composes usePaletteCommands), and the
// input + results list each render through their own sub-component.

import { useFocusTrap } from "../useFocusTrap";
import { MeshCanvas } from "./chat/MeshCanvas";
import { CommandResultsList } from "./commandPalette/CommandResultsList";
import { PaletteInput } from "./commandPalette/PaletteInput";
import { useCommandPalette } from "./commandPalette/useCommandPalette";

export function CommandPalette() {
  const p = useCommandPalette();
  useFocusTrap(p.dialogRef, p.open);

  if (!p.open) return null;

  return (
    <div className="cmdk-overlay" onClick={() => p.setOpen(false)}>
      <MeshCanvas active />
      <div
        className="cmdk"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        ref={p.dialogRef}
        onClick={(e) => e.stopPropagation()}
      >
        <PaletteInput p={p} />
        <CommandResultsList p={p} />
        <div className="cmdk__foot">
          <kbd>up/down</kbd> move <kbd>enter</kbd> run <kbd>esc</kbd> close
        </div>
      </div>
    </div>
  );
}
