# 0035 - Presence equals provisioning: no deployment-shape flags

- Status: accepted
- Date: 2026-08-18
- Related: `docs/SPEC-capability-doctrine.md` (§10, §11.4), decisions 0031, 0030

## Context

The unification plan wants UI flags swapped per deployment mode (Boltrig UI
off / Opbox UI on in combined deployments, the reverse on Boltrig-only). Both
products already have flag seams and both teach a lesson:

- `NEXT_PUBLIC_USE_KERNEL_CHAT` is a Docker build ARG inlined into the client
  bundle — an unbaked image silently bypasses Boltrig, and deploy tooling had
  to grow a pre-flight grep for it. Build-time shape flags are a recorded
  incident shape.
- `BOLTRIG_ADDONS` is env, per-tenant, fail-closed on typos — the better
  seam, but still a switch to leave in the wrong position.
- The Opbox demo already demonstrates the correct pattern: Boltrig is
  optional **by provisioning** — no `depends_on`, every consumer fails
  closed when the connection is absent.

The capability doctrine supplies the AI-surface equivalent: a capability with
zero bindings is simply not projected.

## Decision

Deployment shape is expressed by **what is provisioned, not by flags**:

- The Agents tab renders when a Boltrig connection is configured and healthy;
  it does not render when one is not. No UI flag system is built on either
  side.
- AI capability availability is binding presence: zero Opbox bindings → no
  Opbox capabilities projected (decision 0031).
- No new build-time flags for deployment shape. Endpoint/model selection moves
  to runtime server-probed config so the unbaked-image failure mode dies.
  Existing flags are retired as their surfaces are rebuilt, not duplicated.

## Consequences

- One fewer system to leave misconfigured; the demo's fail-closed
  consumer pattern becomes the norm for optional integration.
- Health of the connection becomes load-bearing for UI visibility — the
  health state the doctrine already requires (§1.A) earns its keep.
- Rollout and rollback become data operations (provision/deprovision a
  connection), auditable through the normal grant/HITL machinery.
