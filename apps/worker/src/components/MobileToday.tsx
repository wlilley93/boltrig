import { useEffect, useState } from "react";
import type { ConversationSummary, HITLRequest } from "@wlilley93/boltrig-web-sdk";

import { client } from "../client";
import { AskBar, EarlierSection, LoadFailedNotice, NeedsYouSection, TodayHeader, WorkingNowSection } from "./MobileTodaySections";

// Today: the mobile home. What needs you, what is working, what happened
// earlier, and one way in at the bottom. Same scoped iOS palette as the
// conversation surface (.mobile-surface), so the two read as one app.

export function MobileToday({
  workspace,
  initials,
  onOpenConversation,
  onNewChat,
  onSettings,
}: {
  workspace: string;
  initials: string;
  onOpenConversation(id: string): void;
  onNewChat(): void;
  onSettings(): void;
}) {
  const [pending, setPending] = useState<HITLRequest[]>([]);
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [busy, setBusy] = useState("");
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.mobileSurface = "today";
    return () => { delete document.documentElement.dataset.mobileSurface; };
  }, []);

  async function load() {
    const [hitl, convo] = await Promise.all([
      client.hitl().catch(() => null),
      client.conversations().catch(() => null),
    ]);
    // A failed read is said, not swallowed: an empty Today that is really an
    // unreachable server would otherwise look like a quiet day.
    setLoadFailed(hitl === null || convo === null);
    if (hitl !== null) setPending(hitl.requests ?? []);
    if (convo !== null) setConversations((convo.conversations ?? []).filter((row) => row.status !== "closed"));
  }
  useEffect(() => { void load(); }, []);

  async function settle(request: HITLRequest, decision: "approve" | "decline") {
    setBusy(request.id);
    try {
      await client.respondHitl(request.id, decision);
      await load();
    } catch {
      // A refusal is the kernel's to report; the row simply stays.
    } finally {
      setBusy("");
    }
  }

  // "Working now" is what the server says is working (the summary's `working`
  // flag is the active-run truth); everything else is Earlier. Nothing is
  // inferred from recency, and nothing is cut off: the list scrolls.
  const working = conversations.find((row) => row.working === true);
  const earlier = conversations.filter((row) => row !== working);
  const quiet = !loadFailed && pending.length === 0 && conversations.length === 0;

  return (
    <div className="mobile-surface">
      <TodayHeader initials={initials} onSettings={onSettings} workspace={workspace} />

      <div className="m-body">
        {loadFailed && <LoadFailedNotice onRetry={() => void load()} />}
        <NeedsYouSection busy={busy} onSettle={(request, decision) => void settle(request, decision)} pending={pending} />
        <WorkingNowSection onOpen={onOpenConversation} working={working} />
        <EarlierSection earlier={earlier} onOpen={onOpenConversation} />
        {quiet && (
          <p className="m-empty">Nothing is waiting and nothing is running. Ask for something below.</p>
        )}
      </div>

      <AskBar onNewChat={onNewChat} />
    </div>
  );
}
