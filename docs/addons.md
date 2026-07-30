# Addons: shipping boltrig alone and boltrig beneath a product

Boltrig ships two ways, and they are the same build:

- **alone** - the product in its own right;
- **as the engine beneath a UI** that provisions it (Opbox today, others next).

An **addon** is the seam between those. It lets an integration contribute what it
knows about itself without that knowledge leaking into the modules every boltrig
ships, and without forking the pinned birth profile.

Nothing here is an authority mechanism. Tools, permissions, credentials and
approval all resolve at the kernel chokepoint exactly as they do with no addon
installed. An addon cannot add a verb, widen a grant, mint a credential or lower
a consequence tier. If you find yourself wanting one to, that is a signal the
change belongs in the kernel, under its gates - not here.

## What an addon contributes

```python
Addon(
    name="billandben",          # alphanumeric (hyphens allowed)
    version="1.0.0",            # numeric dotted
    harness="...",              # prompt fragment (<= 4096 bytes), optional
    adapter_id="billandben",    # the on-behalf adapter, optional
    consequence_hint=fn,        # read THIS server's risk vocabulary, optional
    requirements=(              # kernel-evaluated readiness data, optional
        AddonRequirement(
            id="billandben-adapter",
            kind="adapter",
            ref="billandben",
        ),
    ),
)
```

- **`harness`** is appended *below* the governance floor and the tool harness, so
  the cage always precedes it and cannot be overridden by it. It is bounded
  because the floor is only load-bearing while the model can still see it: an
  addon that contributes pages of text pushes the cage out of attention without
  tripping any hard limit.
- **`adapter_id`** names the consumed server whose session bearer a chat turn
  seals per-run (permission-parity passthrough). Exactly one active addon may
  claim it; two is refused rather than resolved by picking one.
- **`consequence_hint`** reads a consequence tier off a server's own tool
  projection when it declares no structured `consequence` field. It may **raise**
  a tier and can never lower one: `high` is the tier that can require human
  approval, so a hint that returned `low` for a tool whose MCP annotations
  declared `destructiveHint: true` would drop it below the approval gate. The
  highest of all signals wins, not the first - **including between two addons**,
  so one addon's `low` cannot mask another's `high`.

  Consequence hints are read from every **registered** addon, not only the
  activated ones. A reading is not an authority grant and can only raise a tier,
  so gating it on `BOLTRIG_ADDONS` bought no safety and cost the approval gate:
  measured, an opbox tool carrying `riskClass=DESTRUCTIVE` registered as `low`
  wherever the flag was unset, and re-activating the adapter overwrote a stored
  `high` with it. Activation stays meaningful where it belongs - the harness text,
  which is compiled into an attested, hashed birth profile.
- **`requirements`** is declarative readiness data. A requirement may name a
  tenant-scoped adapter record, a cached stack-status component, deployment
  setting presence, or a tenant-scoped credential reference. The kernel
  evaluates those names but never returns them. Requirements cannot carry
  callbacks, verbs, grants or credential material.

## Authenticated runtime inventory

`GET /v1/addons` lists every add-on registered in the running build, whether
active or inactive, and evaluates its requirements in the authenticated
principal's tenant and active workspace. It accepts no caller-supplied scope.
Worker consumes this route in Integrations under **Runtime add-ons**.

The projection distinguishes ready, missing, degraded, unavailable, unverified
and inactive state. It uses persisted records and already-cached health only:
listing never probes an adapter, status provider or credential secret. Harness
text, requirement references, environment names/values, credential metadata,
entry-point paths and evaluator exceptions are never serialized. Activation,
installation and configuration remain deployment or governed control-plane
concerns; the inventory route is read-only.

## Registering one out of tree

A companion product depends on boltrig and declares an entry point:

```toml
[project.entry-points."boltrig.addons"]
billandben = "billandben.boltrig_addon:ADDON"
```

The value may be an `Addon` or a zero-argument callable returning one. Boltrig
discovers it at import; no boltrig code change is required. A broken entry point
raises rather than being skipped - a companion product that silently fails to
load is the failure mode this seam exists to avoid.

In-tree addons (`boltrig/addons/opbox.py`) register the same way, by import.

## Activating one

**Registration is not activation.** An addon does nothing until the deployment
names it:

```
BOLTRIG_ADDONS=opbox
```

Comma-separated for several. A name that is not registered **raises** - a typo
must not quietly ship a boltrig with the integration missing, because that
failure is invisible: the turn completes, the agent apologises, and nothing in
the record says the integration was never loaded.

A boltrig shipping alone sets nothing, activates nothing, and carries no
integration vocabulary in its prompt or its consequence mapping.

## The pinned version composes, it does not fork

The codex kernel-tools lane sends **pinned, hashed** birth instructions. Adding an
integration changes that text, so it must change the pin - but it must not create
a second profile to maintain in parallel.

The profile keeps one name. Its version is the base version plus semver build
metadata naming the active addons:

| deployment | profile version |
|---|---|
| boltrig alone | `1.1.0` |
| boltrig + opbox | `1.1.0+opbox-1.0.0` |

Both the adapter and the admission derive this through the same function, so the
two sides cannot drift. To update the harness text, bump
`KERNEL_TOOLS_BASE_VERSION`; to update an integration's contribution, bump that
addon's `version`. Either moves the pin forward. Neither forks it.

## Sending a chat turn: use an idempotency key

Unrelated to addons, but part of the same contract a product consumes. `POST
/v1/chat` accepts an optional `idempotency_key`, chosen by the client, identifying
**one user message**:

```json
{ "message": "Look up MAT-0002", "idempotency_key": "a7f3…" }
```

A retry that reuses the key is answered as an accepted replay (`message_start` /
`message_end`, both carrying `"replay": true`) instead of convening a second
agent. Without it, a retry starts another run: measured on a live tenant, one
message sent five times 1.4-2.1s apart produced **seven** `agent_spawn` rows — N
times the model spend and N duplicate answers to one question.

Mint the key once per user message, **not** per HTTP attempt, or retries defeat
it. Omitting it is safe and behaves exactly as before.

## Checklist for a new addon

1. Name only tools that **exist** in the tenant's registry. A harness naming an
   unregistered tool teaches the model a call that can only ever be rejected -
   check the live verb table before writing the text, not after.
2. Keep the harness to a paragraph about your own tools. It is not a manual, and
   the cage above it is what keeps the run governed.
3. Ground each rule in a failure you actually measured. Every line of the base
   harness cites one.
4. Set `BOLTRIG_ADDONS` in the deployment that provisions you, and confirm no
   `on-behalf bearer present but NO adapter claims it` warning appears on a live
   turn.
