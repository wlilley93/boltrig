import { api } from "@/api/client";
import { BUILD_NAV, OPERATE_NAV, visibleItems, type ConsoleNavItem } from "@/app/navigation";
import { useIdentity } from "@/identity";
import { navigate } from "@/router";
import { useFetch } from "@/useFetch";
import { PageIntro } from "./ux";

function ZoneCard({ item, meta }: { item: ConsoleNavItem; meta?: string }) {
  return (
    <button className="zone-card" onClick={() => navigate(item.path)}>
      <span className="zone-card__head">
        <strong>{item.label}</strong>
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
      </span>
      <span className="zone-card__body">{item.description}</span>
      {meta && <span className="zone-card__meta">{meta}</span>}
    </button>
  );
}

function ZoneGrid({
  items,
  metadata,
}: {
  items: ConsoleNavItem[];
  metadata: Record<string, string | undefined>;
}) {
  return (
    <div className="zone-grid">
      {items.map((item) => <ZoneCard key={item.id} item={item} meta={metadata[item.id]} />)}
    </div>
  );
}

export function BuildOverviewPanel() {
  const identity = useIdentity();
  const caps = useFetch(() => api.capabilities(), []);
  const workflows = useFetch(() => api.workflows(), []);
  const adapters = useFetch(() => api.adapters(), []);
  const items = visibleItems(BUILD_NAV, identity.role);
  const metadata: Record<string, string | undefined> = {
    automations: workflows.loading && !workflows.data ? "Loading" : `${workflows.data?.workflows.length ?? 0} workflows`,
    router: caps.loading && !caps.data ? "Loading" : `${caps.data?.verbs.length ?? 0} scoped verbs`,
    studio: adapters.loading && !adapters.data ? "Loading" : `${adapters.data?.adapters.length ?? 0} adapters`,
  };

  return (
    <section className="panel zone-overview">
      <PageIntro
        title="Build"
        lead="Shape the agents, workflows and governed capabilities your organisation can run."
        how="Every published change still crosses the control-plane chokepoint; this surface is an authoring workspace, not an authority boundary."
      />
      <div className="zone-overview__signal">
        <span><strong>{caps.data?.verbs.length ?? 0}</strong> capabilities in scope</span>
        <span><strong>{workflows.data?.workflows.length ?? 0}</strong> workflows</span>
        <span><strong>{adapters.data?.adapters.length ?? 0}</strong> adapters</span>
      </div>
      <ZoneGrid items={items} metadata={metadata} />
    </section>
  );
}
export function OperateOverviewPanel() {
  const identity = useIdentity();
  const work = useFetch(() => api.work(), [], 10000);
  const runs = useFetch(() => api.runs(), [], 15000);
  const health = useFetch(() => api.health(), [], 30000);
  const items = visibleItems(OPERATE_NAV, identity.role);
  const activeWork = (work.data?.items ?? []).filter((item) => !["done", "failed"].includes(item.status)).length;
  const failedRuns = (runs.data?.runs ?? []).filter((run) => run.status === "failed").length;
  const adapterIssues = Object.values(health.data?.adapters ?? {}).filter((status) => status !== "ok").length;
  const metadata: Record<string, string | undefined> = {
    kanban: `${activeWork} active items`,
    insight: `${runs.data?.runs.length ?? 0} visible runs`,
    health: adapterIssues === 0 ? "No adapter issues" : `${adapterIssues} adapter issues`,
  };

  return (
    <section className="panel zone-overview">
      <PageIntro
        title="Operate"
        lead="Keep work moving, make deliberate decisions, and inspect the system when it needs attention."
        how="Counts and records remain server-scoped to your effective workspace, role and grants."
      />
      <div className="zone-overview__signal">
        <span><strong>{activeWork}</strong> active work items</span>
        <span><strong>{failedRuns}</strong> failed runs</span>
        <span><strong>{adapterIssues}</strong> adapter issues</span>
      </div>
      <ZoneGrid items={items} metadata={metadata} />
    </section>
  );
}
