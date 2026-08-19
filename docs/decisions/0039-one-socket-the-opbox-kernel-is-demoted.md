# 0039 - One socket: the opbox kernel is demoted, not deleted

- Status: accepted (mechanism confirmed by the Principal, 2026-08-19; relayed
  with the demote-vs-delete tradeoff spelled out and answered directly)
- Date: 2026-08-19
- Related: decision 0031 (opbox ships as a plugin, not ported verbs), decision
  0038 (which component lives where), the docking contract in opbox-frontend
  (PR #209, merged at 29550faa; the opbox side marks the socket sections
  confirmed as of this date)

## Context

Two kernels face each other today. Boltrig's kernel is the agent plane. Opbox's
Rust kernel is the product/verb authority: RLS, tenancy, tracked changes, and a
registry that has grown from 358 verbs (2026-06-08) to 914 across 111 domains,
of which 216 are deliberately never MCP-exposed. The seam between them has been
tried in one shape already - the opbox kernel REGISTERED with boltrig as a peer,
through a kernel /mcp door and a standing `opbox_key_` agent key - and that
shape has failed measurably three times:

- 633 registered rows exceeded a 500-row snapshot cap and left the boltrig
  kernel unbootable;
- a wildcard grant met the 128-tool Codex attestation bound;
- the kernel door's noun-first naming versus the frontend door's verb-first
  naming meant a skill enumerated verbs in one dialect while the tenant ran
  the other - zero resolved, and opbox reach was nil for three days.

The Principal's framing, quoted because it is the decision: "I prefer boltrig
to own - if it were cables, I'd rather opbox declare female ports than male
wires." And on the kernel itself, the confirmed mechanism:

> The opbox Rust kernel stops being a PEER - never registered with boltrig, no
> agent key, invisible to the agent plane, reachable only behind opbox's one
> socket. Estate-level "one kernel, boltrig's" becomes TRUE. It survives as the
> ENGINE inside the opbox capability pack, holding RLS, tenancy, tracked
> changes and the verbs deliberately never MCP-exposed.

Demote, not delete: this repo's own committed design already refused the port
("Do not replace the Opbox kernel" is a stated non-goal), and boltrig's LOW/HIGH
consequence split cannot carry opbox's four-tier split that keeps 216 verbs off
MCP entirely. Deleting the Rust kernel would mean rewriting an authority layer
that already works, to gain a sentence.

## Decision

Boltrig owns the seam, and the seam is ONE socket: opbox's frontend verbs door,
per-user runBearer, fail-closed, `opbox.*` namespaced. The opbox kernel is
demoted to an engine behind that socket. Four items follow, in this order:

1. **The health check lands first - and it already has.** Under one socket, the
   MCP consumer's health string is the seam's entire observability, and until
   PR #306 it was a green that could not go red: `health()` answered "ok" off
   specs that `control_rehydrate` replays from the store at boot, no network
   touched. It now answers "ok" only after a round trip has ANSWERED in this
   process, "degraded" while specs are held but nothing has been reached
   (`boltrig/adapters/mcp_consumer.py`, pinned by tests that fail against the
   old implementation). Expect one honest regression when it deploys: /healthz
   reports "degraded" for the consumed server until a live round trip
   succeeds. That is the amber that replaces a false green, not a fault.
2. **De-register the kernel /mcp door and retire the `opbox_key_` agent key.**
   The registration is the male wire: a standing machine credential with
   kernel-wide reach. Removing it also kills the noun-first/verb-first split at
   the root, which is what cost the three days.
3. **Re-probe against the frontend door** to replace the 2026-07-22 snapshot of
   633 rows, through the SEC-22 probe/activate mechanism. A re-probe against
   the CURRENT registry is ~698 MCP-exposable rows, not 633; the snapshot cap
   and admission bounds must be checked against that number before activation,
   not after.
4. **Cap by profile, not by thinning the door.** The door serves the full
   catalogue at registration-time tools/list deliberately. The 128-tool
   attestation limit is a property of one profile, so curated per-profile
   grants - never a wildcard - are the fix. The wildcard-vs-attestation
   collision is the recurrence this item exists to prevent.

Standing machine credentials across the seam are BRIDGES with expiries, not
patterns. The `opbox-demo-admin` PAT minted 2026-08-19 (30 days, revocable by
name) is the worked example: it exists so a demo build can carry kernel chat
before per-user identity lands, and it retires when the contract's identity
line (boltrig owns auth and membership; the user's own identity is the bearer)
replaces it.

## Consequences

- The agent plane sees exactly one opbox surface, in one naming dialect.
- The Rust kernel keeps everything it is uniquely good at and loses only its
  standing credential and its peer status.
- The seam's health string becomes load-bearing, which is why item 1 precedes
  item 2 rather than following it.
- A cross-estate operational note travels with this decision: the machine-wide
  heavy-job lock is now ONE lock. Opbox's build lock joins the lock that
  boltrig's pre-push guard holds (weight-based, not name-based), because two
  conventions with one participant each excluded nothing - measured on
  2026-08-19 when a 10 GiB build and an unmetered test chain nearly froze the
  box that hosts both repos.
