import { lazy } from "react";
import type { ReactNode } from "react";

import { AgentSlide } from "@/panels/AgentSlide";
import { AdminPanel } from "@/panels/AdminPanel";
import { AgentsSlide } from "@/panels/AgentsSlide";
import { ApprovalsPanel } from "@/panels/ApprovalsPanel";
import { AutomationsSlide } from "@/panels/AutomationsSlide";
import { ChannelsPanel } from "@/panels/ChannelsPanel";
import { DevConsolePanel } from "@/panels/DevConsolePanel";
import { EvalPanel } from "@/panels/EvalPanel";
import { HomePanel } from "@/panels/HomePanel";
import { HealthPanel } from "@/panels/HealthPanel";
import { InsightPanel } from "@/panels/InsightPanel";
import { KanbanPanel } from "@/panels/KanbanPanel";
import { MemoryPanel } from "@/panels/MemoryPanel";
import { MePanel } from "@/panels/MePanel";
import { RouterPanel } from "@/panels/RouterPanel";
import { RunsPanel } from "@/panels/RunsPanel";
import { StepSlide } from "@/panels/StepSlide";
import { AccountSlide } from "@/panels/settings/AccountSlide";
import { AppearanceSlide } from "@/panels/settings/AppearanceSlide";
import { DeveloperSlide } from "@/panels/settings/DeveloperSlide";
import { NotificationsSlide } from "@/panels/settings/NotificationsSlide";
import { OrganisationSlide } from "@/panels/settings/OrganisationSlide";
import { PersonalAgentSlide } from "@/panels/settings/PersonalAgentSlide";
import { PrivacySlide } from "@/panels/settings/PrivacySlide";
import { SecuritySlide } from "@/panels/settings/SecuritySlide";
import { SettingsAnchorSlide } from "@/panels/settings/AnchorSlide";
import { BuildOverviewPanel, OperateOverviewPanel } from "@/panels/ZoneOverviewPanel";

// Studio pulls in the @xyflow/react canvas; lazy-load it so that heavy chunk
// only downloads when the user opens the authoring hub (code-split, Fix 5).
const StudioPanel = lazy(() =>
  import("@/panels/StudioPanel").then((m) => ({ default: m.StudioPanel })),
);

// Chat pulls in the unified/remark Markdown parser stack. Keep it out of the
// initial shell and load it only when the deck first mounts the Chat row.
const ChatPanel = lazy(() =>
  import("@/panels/ChatPanel").then((m) => ({ default: m.ChatPanel })),
);

type PanelFactory = () => ReactNode;

const OPS_PANELS: Record<string, PanelFactory> = {
  home: () => <HomePanel />,
  runs: () => <RunsPanel />,
  build: () => <BuildOverviewPanel />,
  operate: () => <OperateOverviewPanel />,
  router: () => <RouterPanel />,
  studio: () => <StudioPanel />,
  dev: () => <DevConsolePanel />,
  kanban: () => <KanbanPanel />,
  approvals: () => <ApprovalsPanel />,
  insight: () => <InsightPanel />,
  eval: () => <EvalPanel />,
  memory: () => <MemoryPanel />,
  health: () => <HealthPanel />,
  admin: () => <AdminPanel />,
  channels: () => <ChannelsPanel />,
  me: () => <MePanel />,
};

export const SETTINGS_PANELS: Record<string, PanelFactory> = {
  settings: () => <SettingsAnchorSlide />,
  account: () => <AccountSlide />,
  appearance: () => <AppearanceSlide />,
  notifications: () => <NotificationsSlide />,
  developer: () => <DeveloperSlide />,
  agent: () => <PersonalAgentSlide />,
  privacy: () => <PrivacySlide />,
  security: () => <SecuritySlide />,
  organisation: () => <OrganisationSlide />,
};

// The deck cell -> panel mapping. Module-level so its identity stays stable
// across renders. Unknown cells render null (the deck only asks for cells the
// row model names, so this is a type-level backstop).
export function renderCell(rowId: string, colKey: string): ReactNode {
  if (rowId === "chat") return <ChatPanel />;
  if (rowId === "agents") {
    return colKey === "agents" ? <AgentsSlide /> : <AgentSlide agentName={colKey} />;
  }
  if (rowId === "automations") {
    return colKey === "automations" ? <AutomationsSlide /> : <StepSlide stepKey={colKey} />;
  }
  const settingsPanel = SETTINGS_PANELS[colKey];
  if (rowId === "settings" && settingsPanel) return settingsPanel();
  const opsPanel = OPS_PANELS[colKey];
  if (rowId === "ops" && opsPanel) return opsPanel();
  return null;
}
