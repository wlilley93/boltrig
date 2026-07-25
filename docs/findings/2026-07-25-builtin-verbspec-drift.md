# A builtin adapter's VerbSpec change never reaches a tenant that already has it

Date: 2026-07-25
Status: gap identified, mitigated by an explicit resync tool; the boot-time
question below is a genuine design fork and is NOT decided here.

## The gap

A builtin adapter's verb data - consequence, schemas, description, rate limit -
is AUTHORED in code (`VerbSpec`) but SERVED from the store: `register_adapter`
-> `registry.register_adapter_verbs` -> `store.upsert_verb`. That upsert runs
only when the adapter is registered into a tenant.

On boot, `_rehydrate_store_adapters` (`boltrig/api/bootstrap.py:195`) rebuilds
live instances only for rows it can reconstruct HONESTLY, which today means
`boltrig.adapters.mcp_consumer` rows. A `source='builtin'` row is skipped with
`"has no honest boot reconstruction; leaving it a store-only row"`.

Consequence: a builtin registered into a tenant ONCE keeps its original verb
rows forever. Editing the code changes nothing for that tenant - not on
restart, not on redeploy, not on rebuild.

## Why it bit

`[2026] VJS-APPEAL 1` (LJ-2) directs that a mis-classified verb be recalibrated
as DATA, and `scripts/calibration-audit.py` reads the STORE. The audit found
ms_graph's `document.create` / `document.update` at LOW while every other write
in that adapter was HIGH. Setting `consequence="high"` in `ms_graph.py` and
redeploying left the kernel still gating on the stored LOW - the fix looked
landed and was inert. Verified on the beelink dev box: after redeploy the store
still read `document.create|low`.

## Mitigation (shipped)

`scripts/resync-builtin-verbs.py <builtin> [--tenant T] [--dry-run]`
re-registers a builtin's verbs through `Kernel.register_adapter` - the same
seam boot uses, so nouns, bindings and rate limits stay consistent. `--dry-run`
reports the drift without writing. Applied to the dev box: the two verbs are
now HIGH in the store and the audit's HIGH count went 582 -> 584.

**Run it on every tenant that has the adapter registered after changing a
builtin's VerbSpec**, or the code and the gate disagree.

## Fleet propagation (all three stores)

The drift was present on every deployment, because it dates from whenever each
tenant first registered the builtin:

| store | route taken | result |
| --- | --- | --- |
| beelink dev (`boltrig`) | `resync-builtin-verbs.py` through the seam | HIGH |
| jellytot-prod CV (`cvboltrig`, GHCR 0.3.0) | same, over an SSH tunnel | HIGH |
| jellytot-prod boltrig.io (`boltrig`, local 0.1.0) | targeted UPDATE (see below) | HIGH |

The boltrig.io stack is six days old and its schema PREDATES `verbs.idempotency_mode`,
so today's code cannot read it (`KeyError: 'idempotency_mode'` out of
`store/rows.py::_verb`). Pointing new code at an old-schema store is the exact
db-push/kernel-wipe class of hazard, so the seam was NOT forced there: only the
one drifted column was set, and the next image roll re-registers the same values
as a no-op. Those two verbs had never been dispatched on that stack
(`dispatch_count=0`), so the change could not disturb a live flow.

Rolling the prod IMAGES so the code fix (and the rest of today's work) reaches
those boxes is a separate, Principal-gated action and has not been done.

## Not every LOW is a defect: the audit now splits by locus

Running the audit against CV first surfaced `opbox.remove_member` and
`opbox.update_member_role` at LOW, which LOOKS like the same finding and is not.
Those verbs are consumed from opbox's app server; opbox gates them at its OWN
kernel (autonomy level 2, enforced on the per-run clamped runBearer,
`[2026] CC-OPBOX 115`). `[2026] VJS-PC 20` holds governance is defined by the
ENFORCING chokepoint's LOCUS, not the cardinality of gates, and
`[2026] CC-OPBOX 1` puts a domain's calibration on its own SoR kernel - so a
boltrig-side gate there would be a check standing BESIDE the record rather than
derived from it. Their LOW is correct, and NO change was made to the client
tenant's data.

`scripts/calibration-audit.py` now encodes that distinction: it resolves each
candidate's binding to its adapter and reports first-party (boltrig is the sole
chokepoint) separately from consumed (governed at a foreign SoR locus,
informational). Unknown provenance is reported as sole-chokepoint, so the audit
fails toward asking a human. Both stores now report only the one justified LOW
(`ticket.create`, the in-memory demo adapter).

## The open fork (not decided)

Should boot RECONSTRUCT builtin adapter rows from their `module_ref` (a builtin
has an in-tree deterministic `build()`, so it arguably meets the same "honest"
bar the mcp_consumer path does)? It would close this drift permanently and also
un-phantom builtin rows, which are currently present in the store but not live
in the loader.

The reason not to do it unilaterally: boot-time re-registration would let the
CODE's spec silently overwrite any per-tenant authoring of those same verbs
made through the control plane. Code-wins-over-tenant-authoring-on-every-boot
is a first-impression governance question about where the authority for verb
data sits, not a mechanical fix. It belongs in front of the court with the
control-plane authoring path enumerated as evidence.
