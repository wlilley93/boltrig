import type { BoltrigClient } from "@wlilley93/boltrig-web-sdk";
import { BoltrigApiError } from "@wlilley93/boltrig-web-sdk";

import * as chat from "./chat";
import * as conv from "./conversations";
import * as sett from "./settings";

/** What this adapter actually implements against a Hermes cell.
 *
 *  Every entry here is backed by a route on `cell_proxy.ALLOWED` or by the
 *  control plane. Nothing is stubbed to look successful: a method that cannot
 *  work is absent (below), not faked.
 */
const adapter = {
  // Chat and runs
  streamChat: chat.streamChat,
  followConversation: chat.followConversation,
  cancelRun: chat.cancelRun,
  respondHitl: chat.respondHitl,
  hitl: chat.hitl,

  // Conversations, over Hermes sessions
  conversations: conv.conversations,
  conversationsPage: conv.conversationsPage,
  conversation: conv.conversation,
  deleteConversation: conv.deleteConversation,
  renameConversation: conv.renameConversation,

  // Identity, settings and read-only cell surfaces
  meSettings: sett.meSettings,
  putMeSettings: sett.putMeSettings,
  refreshSession: sett.refreshSession,
  chatModelChoices: sett.chatModelChoices,
  chatConfig: sett.chatConfig,
  capabilities: sett.capabilities,
  health: sett.health,
  skills: sett.skills,
  toolsets: sett.toolsets,
};

/** Names the UI PROBES with `typeof client.x === "function"` and that nothing
 *  here backs. They must read as ABSENT, so the feature hides itself.
 *
 *  Absent - not throwing, and not rejecting. A probe is a synchronous property
 *  read during render: anything that throws there takes out the component, and
 *  a rejecting function would make the probe PASS and the feature render itself
 *  into a broken state.
 *
 *  Derived from the tree, never remembered:
 *    grep -rhoE 'typeof client\.[a-zA-Z]+' src/ | sed 's/typeof client\.//' | sort -u
 *  minus every name `adapter` implements. Recompute it after any route change;
 *  a stale list silently re-enables a dead feature. */
const ABSENT = new Set([
  "approvalPosture", "auditSearch", "budgets", "calls", "createCall",
  "createWork", "currentCall", "currentOrg", "familiarPhenotype",
  "memoryForget", "memoryImprove", "memoryIngest", "memoryRemember",
  "meNotifications", "namedAgents", "putApprovalPosture", "readiness", "runs",
  "sensing", "sensingCapability", "workspaces",
]);

/** Property names that must never be answered with a function.
 *
 *  `then` is the one that bites. Any code that awaits this object, or returns
 *  it from an async function, reads `.then` to decide whether it is a thenable
 *  - so handing back a function there turns the client into a promise that
 *  never settles. The rest is React's and the test runner's introspection. */
const NOT_A_METHOD = new Set([
  "then", "catch", "finally", "toJSON", "$$typeof", "constructor", "prototype",
  "nodeType", "tagName", "asymmetricMatch", "@@__IMMUTABLE_RECORD__@@",
]);

/** The client the whole UI talks to.
 *
 *  TYPED AS THE SDK CLIENT, DELIBERATELY. The v1 UI calls 242 SDK methods
 *  across 518 call sites. Typing this as the object literal above narrows the
 *  client to what the adapter implements and turns every other call site into a
 *  hard type error - measured at 539 of them, in 102 files, none of which is
 *  the UI's fault. The cast is the seam: the TYPES stay the SDK's, and the
 *  runtime below decides what an unimplemented method does.
 *
 *  An unimplemented method returns a function that REJECTS. It never throws on
 *  property access: the views guard with `.catch(() => setLoadState("unavailable"))`,
 *  which catches a rejected promise and cannot catch a synchronous throw from a
 *  property read. */
export const client = new Proxy(adapter, {
  get(target, prop, receiver) {
    const value = Reflect.get(target, prop, receiver);
    if (value !== undefined) return value;
    if (typeof prop !== "string") return undefined;
    if (NOT_A_METHOD.has(prop) || ABSENT.has(prop)) return undefined;
    return () => Promise.reject(
      new BoltrigApiError(
        501,
        { reason: "unsupported", method: prop },
        `${prop} is not available against a Hermes cell`,
      ),
    );
  },
}) as unknown as BoltrigClient;

export { ABSENT, adapter };
