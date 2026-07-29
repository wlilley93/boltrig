# Goal: the console mounts with its stack

**Written 2026-07-29.** An increment of `opbox-prod/docs/GOAL-boltrig-federation.md`. That one says
boltrig is the agent-of-record under every app. This one is about the console that ships with it,
and about the fact that a client currently cannot reach theirs at all.

---

## The statement

> **Wherever a boltrig stack ships, its operator console is reachable at `/boltrig` on that stack's
> own host, served by the same artefact that serves every other mount.** Not a subdomain to
> provision, not a build variant to remember, not a route someone adds by hand on the box. A client
> consuming boltrig - directly or through the SDK - gets the console at
> `<their-host>/boltrig` because that is what the stack is, not because a step was performed.

Done means: stand up tenant N+1 from the template, open `<tenant-host>/boltrig`, and the console is
there, running the byte-identical image that `app.boltrig.io` runs.

## Why this, and what it is fixing

Today `app.boltrig.io` reaches the solo stack on `127.0.0.1:8620`. Classical Visas' console sits on
`127.0.0.1:8621` and appears **zero times** in the Caddyfile. The client's own operator console has
no public route. Nobody decided that; it is simply what happens when reachability is a manual step
and the manual step is the thing that gets forgotten.

The alternative to a path convention is a hostname per stack: `boltrig.<client>.com`, DNS, a
certificate, a tunnel ingress rule, an entry in the Caddyfile. Five artefacts per tenant, each of
which can be missing on its own. We already ran this experiment with signing: `sign.opbox.app`
CNAME'd to a retired Fly app while the envelopes lived elsewhere, so CV's signing links pointed at a
host that had never held their data. The cure then was the same as the cure now: serve it on the
tenant's own host under a path (`<tenant-host>/sign/{token}`, `SIGN_TENANT_PATH`). This goal
generalises that disposition to the console.

The corollary is a discipline: **the mount point is data, not a build input.** The moment a mount
path is baked into an image, "which image does this client run" becomes a question with more than
one answer, and drift between source, demo and CV follows by construction.

## What makes it tractable

Three facts about the code, established 2026-07-29:

1. **`ui/src/router.ts` is a hash router.** Every deep link is `#/runs/123`, so the server-side path
   is only ever the mount point. The usual hard part of subpath mounting - deep-route SPA fallback
   at arbitrary depth - does not exist here.
2. **`window.location.pathname` therefore IS the mount prefix**, at runtime, with no configuration.
   `/` standalone, `/boltrig/` under a tenant.
3. **All four kernel fetches go through one constant.** `BASE` in `ui/src/api/transport.ts` is the
   single place the mount reaches the wire (`request` there, two streaming fetches in
   `ui/src/api/sse.ts`, one in `ui/src/api/domains/knowledge.ts`), so deriving it once mounts the
   whole app.

**A correction, recorded because it nearly shipped an inert change.** An earlier draft of this goal
claimed subpath mounting was already precedent here, citing an `apps/worker` image that packages the
console under `/operator/` via a `BOLTRIG_UI_BASE` knob in `vite.config.ts`, pinned by an invariant
test. **None of that is on `main`.** There is no `apps/` directory, no `base:` line in
`vite.config.ts`, and no such test: all of it is uncommitted work in one local tree, which is where
it was read from and mistaken for shipped code. The consequence was concrete, not cosmetic. Setting
`BOLTRIG_UI_BASE` in the image does nothing unless something reads it, so the first version of this
work would have built with absolute `/assets/...` and broken the mount it was written to enable. It
looked verified because the build was run in the tree that had the uncommitted knob, not in the
branch. **Read the branch, not the tree you happen to be standing in** - the same error, in a
different costume, as trusting a symlinked binary for a before/after.

## Criteria

- **M1** One artefact. `ghcr.io/wlilley93/boltrig-ui:<v>` serves correctly at `/` and at `/boltrig/`
  with no rebuild, no env var at the container, and no per-tenant image tag.
- **M2** The mount is derived, never declared. Nothing in the tenant's compose, env or manifest
  names the mount path. Move the mount and the app follows without being told.
- **M3** The negative control passes. A derivation that prefixes everything would satisfy M1's
  happy path and break the standalone. The standalone-at-root case is a test in its own right, and
  it has been observed red.
- **M4** Reachability is asserted at the destination, and **the assertion reaches the API**. A gate
  fetches `<tenant-host>/boltrig/` and asserts the console's own index came back, not the app's 404
  and not a 200 from the wrong service - and then calls the kernel through the same mount and
  asserts an *authentication* answer (401), never a *transport* one (400/404/502). "The Caddyfile
  contains a block" is a fact about a file.

  This limb is not theoretical. Measured on Classical Visas before the mount existed:

  | request | result |
  |---|---|
  | `GET /` with `Host: classicalvisas.opbox.app` | **200**, the SPA renders |
  | `GET /v1/skills` with the same Host | **400 Invalid host header** |

  The kernel's `BOLTRIG_ALLOWED_HOSTS` listed only `cv-boltrig-kernel-1,kernel,localhost,127.0.0.1`,
  so it answered on the loopback address it had always been reached by and refused the hostname a
  browser would send. An index-only gate passes that deployment. The user gets a console that loads
  and then fails on every call, which is the same class as a green health check over a dead feature.
- **M5** Tenant N+1 inherits it. `opbox-prod/scripts/new-tenant.sh` renders the mount; standing up a
  tenant without it is not a thing anyone can accidentally do.
- **M6** Exposure is a decision with evidence behind it. Before a console is opened on a
  client-facing host, three things are shown, not assumed: the kernel is not a dev-identity build,
  an unauthenticated request is refused by `AuthGate`, and the session cookie's `Path` scopes it to
  the mount.

## The invariant this program is most likely to violate quietly

`app.boltrig.io` sits behind Cloudflare Access. `classicalvisas.opbox.app` does not - clients
authenticate to Opbox there. Mounting the console on the tenant host therefore **moves the whole
perimeter onto the console's own login**. That trade may well be right, and it is the same trade the
signing cutover made deliberately (`opbox-prod/docs/SIGN-CUTOVER-PLAN-2026-07-24.md` records losing
separate-origin isolation in exchange for killing the stranded-host class). What is not acceptable
is making it by accident, in a Caddyfile edit, without writing down that it was made.

So: **M6 gates M4.** No console is reachable before its perimeter is evidenced.

## Non-goals

- Replacing `app.boltrig.io`. The standalone console keeps its hostname and its CF Access perimeter.
- A hostname per tenant console. Explicitly rejected above; that is the class this goal exists to
  end.
- Merging the console into the Opbox frontend. They are two surfaces over one kernel
  (`GOAL-boltrig-federation.md`), and neither is a copy of the other.

## Phases

| Phase | What lands | Blast radius |
|---|---|---|
| 1 | Runtime mount derivation in `ui/` (relative asset base + pathname-derived API prefix) | the shipped `boltrig-ui` image |
| 2 | M6 evidence, then the edge mount on `classicalvisas.opbox.app` | one client, one Caddyfile |
| 3 | The mount folded into `new-tenant.sh` and the tenant template | every future tenant |

Phase 1 is the only phase that changes an artefact tenants run. Phases 2 and 3 are configuration and
templating.

## Related

- `opbox-prod/docs/GOAL-boltrig-federation.md` - one kernel under every app; this is its console
  corollary.
- `opbox-prod/GOAL-delivery.md` - D1/D2: the check reads the destination, and has been seen red.
  M3 and M4 are that discipline applied here.
- `opbox-prod/docs/SIGN-CUTOVER-PLAN-2026-07-24.md` - the tenant-path precedent, including what it
  cost.
- `scripts/check_prose_references.py` - the gate that caught three of this document's own references
  pointing at files in another repository. It is why the paths above carry their repo.
