import { useMemo } from "react";

import type { CapabilitiesResponse } from "@/api/types";
import { navigate } from "@/router";

export interface Cmd {
  id: string;
  label: string;
  hint: string;
  run: () => void;
}

const PAGES: ReadonlyArray<{ id: string; label: string }> = [
  { id: "home", label: "Home" },
  { id: "router", label: "Router" },
  { id: "studio", label: "Studio" },
  { id: "dev", label: "Dev console" },
  { id: "chat", label: "Chat" },
  { id: "kanban", label: "Kanban" },
  { id: "approvals", label: "Approvals" },
  { id: "insight", label: "Insight" },
  { id: "eval", label: "Eval" },
  { id: "memory", label: "Memory" },
  { id: "me", label: "Me" },
  { id: "settings", label: "Settings" },
];

export function usePaletteCommands(
  caps: CapabilitiesResponse | null,
  q: string,
): { commands: Cmd[]; filtered: Cmd[] } {
  const commands: Cmd[] = useMemo(() => {
    const pages: Cmd[] = PAGES.map((p) => ({
      id: `page:${p.id}`,
      label: p.label,
      hint: "Page",
      run: () => navigate(`/${p.id}`),
    }));
    const verbs: Cmd[] = (caps?.verbs ?? []).map((v) => ({
      id: `verb:${v.id}`,
      label: v.id,
      hint: `Run verb (${v.noun})`,
      run: () => navigate("/dev"),
    }));
    return [...pages, ...verbs];
  }, [caps]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return commands.slice(0, 30);
    return commands.filter((c) => c.label.toLowerCase().includes(needle)).slice(0, 30);
  }, [commands, q]);

  return { commands, filtered };
}
