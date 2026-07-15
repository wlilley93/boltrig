import { useMemo } from "react";

import type { CapabilitiesResponse, RunsResponse, WorkflowsResponse } from "@/api/types";
import { BUILD_NAV, OPERATE_NAV, PRIMARY_NAV, visibleItems } from "@/app/navigation";
import { setDevInvokePrefill } from "@/devInvokePrefill";
import { navigate, openRun } from "@/router";

export interface Cmd {
  id: string;
  label: string;
  hint: string;
  kind: Exclude<CommandKind, "all">;
  keywords?: string;
  run: () => void;
}

export type CommandKind = "all" | "page" | "workflow" | "run" | "verb";

export function usePaletteCommands(
  caps: CapabilitiesResponse | null,
  workflows: WorkflowsResponse | null,
  runs: RunsResponse | null,
  role: string,
  q: string,
  kind: CommandKind = "all",
): { commands: Cmd[]; filtered: Cmd[] } {
  const commands: Cmd[] = useMemo(() => {
    const nav = [
      ...PRIMARY_NAV,
      ...visibleItems(BUILD_NAV, role),
      ...visibleItems(OPERATE_NAV, role),
      { id: "settings", label: "Settings", path: "/settings", description: "Account and console preferences" },
    ];
    const pages: Cmd[] = nav.map((page) => ({
      id: `page:${page.id}`,
      label: page.label,
      hint: "Page",
      kind: "page",
      keywords: page.description,
      run: () => navigate(page.path),
    }));
    const verbs: Cmd[] = (caps?.verbs ?? []).map((verb) => ({
      id: `verb:${verb.id}`,
      label: verb.id,
      hint: `Run verb · ${verb.noun}`,
      kind: "verb",
      keywords: `${verb.noun} capability action`,
      run: () => {
        setDevInvokePrefill({ noun: verb.noun, verb: verb.id });
        navigate("/dev");
      },
    }));
    const workflowCommands: Cmd[] = (workflows?.workflows ?? []).map((workflow) => ({
      id: `workflow:${workflow.id}`,
      label: workflow.id,
      hint: `Workflow · v${workflow.version} · open to review and run`,
      kind: "workflow",
      keywords: `workflow open run trigger execute ${workflow.source} ${(workflow.intent_tags ?? []).join(" ")}`,
      run: () => navigate(`/automations/${encodeURIComponent(workflow.id)}`),
    }));
    const runCommands: Cmd[] = (runs?.runs ?? [])
      .filter((run) => Boolean(run.run_id))
      .map((run) => ({
        id: `run:${run.run_id}`,
        label: run.intent || run.run_id || "Run",
        hint: `Run · ${run.status}`,
        kind: "run",
        keywords: `${run.run_id} ${run.work_item} ${run.owner ?? ""}`,
        run: () => openRun(run.run_id as string),
      }));
    return [...pages, ...verbs, ...workflowCommands, ...runCommands];
  }, [caps, workflows, runs, role]);

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const inKind =
      kind === "all" ? commands : commands.filter((command) => command.kind === kind);
    if (!needle) return inKind.slice(0, 36);
    const terms = needle.split(/\s+/).filter(Boolean);
    return inKind
      .filter((command) => {
        const haystack =
          `${command.label} ${command.hint} ${command.keywords ?? ""}`.toLowerCase();
        return terms.every((term) => haystack.includes(term));
      })
      .slice(0, 36);
  }, [commands, q, kind]);

  return { commands, filtered };
}
