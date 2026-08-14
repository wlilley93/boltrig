import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
  type SetStateAction,
} from "react";

import { characterToSettings, saveCharacterLocal } from "../../character";
import { client } from "../../client";
import type { WorkerRoute } from "../../routes";
import { useCharacters, type Character } from "../characters";
import { useFamiliarBody } from "../StageBody";

interface CompanionSwitcherProps { route: WorkerRoute }
interface CompanionMenuProps {
  busy: boolean;
  installed: Character[];
  menuRef: RefObject<HTMLDivElement>;
  message: string;
  onChoose(id: string): void;
  onClose(): void;
  onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void;
  selectedId: string;
}
interface CompanionMenuEffects {
  menuRef: RefObject<HTMLDivElement>;
  open: boolean;
  route: WorkerRoute;
  setMessage: Dispatch<SetStateAction<string>>;
  setOpen: Dispatch<SetStateAction<boolean>>;
  triggerRef: RefObject<HTMLButtonElement>;
}

async function persistCharacter(id: string): Promise<string | null> {
  try {
    const result = await client.putMeSettings({ settings: characterToSettings(id) });
    return result.status === "ok"
      ? null
      : result.reason ?? "Your companion could not be saved.";
  } catch {
    return "Your companion could not be saved.";
  }
}

function useCompanionMenuEffects({
  menuRef, open, route, setMessage, setOpen, triggerRef,
}: CompanionMenuEffects) {
  useEffect(() => { setOpen(false); setMessage(""); }, [route, setMessage, setOpen]);
  useEffect(() => {
    if (!open) return;
    menuRef.current
      ?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]')
      ?.focus();
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [menuRef, open, setOpen, triggerRef]);
}

function moveMenuFocus(
  event: ReactKeyboardEvent<HTMLDivElement>,
  setOpen: Dispatch<SetStateAction<boolean>>,
  triggerRef: RefObject<HTMLButtonElement>,
) {
  if (event.key === "Tab") {
    event.preventDefault();
    setOpen(false);
    (event.shiftKey
      ? triggerRef.current
      : document.querySelector<HTMLButtonElement>(".side-top .side-icon-button"))?.focus();
    return;
  }
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
  const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>(
    '[role="menuitemradio"]:not(:disabled)',
  )];
  const current = items.indexOf(document.activeElement as HTMLButtonElement);
  const delta = event.key === "ArrowDown" ? 1 : -1;
  const next = current < 0 && delta < 0
    ? items.length - 1
    : (current + delta + items.length) % items.length;
  event.preventDefault();
  items[next]?.focus();
}

function CompanionMenu(props: CompanionMenuProps) {
  return (
    <>
      <button aria-label="Close companion menu" className="side-menu-scrim companion-menu-scrim" onClick={props.onClose} tabIndex={-1} type="button" />
      <div aria-label="Companion" className="side-menu companion-menu" onKeyDown={props.onKeyDown} ref={props.menuRef} role="menu">
        {props.installed.map((character) => (
          <button
            aria-checked={character.id === props.selectedId}
            className="companion-menu-row"
            disabled={props.busy}
            key={character.id}
            onClick={() => props.onChoose(character.id)}
            role="menuitemradio"
            tabIndex={-1}
            type="button"
          >
            <span className="companion-menu-copy">
              <strong>{character.name}</strong>
              <small>{character.blurb}</small>
            </span>
            {character.id === props.selectedId && <span aria-hidden className="companion-menu-check">✓</span>}
          </button>
        ))}
        {props.message && <p className="companion-menu-error" role="alert">{props.message}</p>}
      </div>
    </>
  );
}

/** The selected companion is product state, so the shell names it instead of
 * displaying a static Boltrig wordmark. */
export function CompanionSwitcher({ route }: CompanionSwitcherProps) {
  const selectedId = useFamiliarBody();
  const installed = useCharacters();
  const selected = installed.find(({ id }) => id === selectedId) ?? installed[0];
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  useCompanionMenuEffects({ menuRef, open, route, setMessage, setOpen, triggerRef });

  const close = () => { setOpen(false); triggerRef.current?.focus(); };
  const choose = async (next: string) => {
    if (busy) return;
    if (next === selectedId) return close();
    setBusy(true);
    setMessage("");
    saveCharacterLocal(next);
    const error = await persistCharacter(next);
    if (error) { saveCharacterLocal(selectedId); setMessage(error); } else { close(); }
    setBusy(false);
  };

  if (!selected) return null;
  return (
    <div className="companion-switcher">
      <button aria-expanded={open} aria-haspopup="menu" aria-label={`Companion: ${selected.name}`} className="companion-switcher-trigger" onClick={() => { setOpen((value) => !value); setMessage(""); }} ref={triggerRef} type="button">
        <span>{selected.name}</span>
        <svg aria-hidden fill="none" height="12" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="12"><polyline points="8 10 12 14 16 10" /></svg>
      </button>
      {open && <CompanionMenu busy={busy} installed={installed} menuRef={menuRef} message={message} onChoose={(id) => void choose(id)} onClose={close} onKeyDown={(event) => moveMenuFocus(event, setOpen, triggerRef)} selectedId={selected.id} />}
    </div>
  );
}
