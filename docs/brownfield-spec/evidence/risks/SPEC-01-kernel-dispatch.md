# Risks harvested from SPEC-01-kernel-dispatch.md

RISK: `dispatch.py`'s own module docstring lists `validate params` before
`grant check`, and its body does the reverse. A reader trusting the docstring at
the top of the file gets the order backwards.
[`boltrig/kernel/dispatch.py:7`](../../../boltrig/kernel/dispatch.py) `"validate params          (SchemaValidationError, SEC-21)"`
against [`boltrig/kernel/dispatch.py:507`](../../../boltrig/kernel/dispatch.py) `"# 2. grant check (SEC-07) BEFORE validation"`.

---

RISK: `docs/ARCHITECTURE.md`'s dispatch table places idempotency replay AFTER the
HITL gate and the rate limit, which is the opposite of the code and of the SEC-15
invariant. An operator reasoning about replay from that table will get the
approval-spend behaviour wrong.
[`docs/ARCHITECTURE.md:55`](../../../docs/ARCHITECTURE.md) `"| 6 | Idempotency replay (return the prior result) |"`.

---

RISK: `boltrig/kernel/mcp.py` gates schema disclosure on a comment that states the
order backwards and cites line numbers that no longer point at those steps:
"params are validated before grants are checked (dispatch.py:520 then :524)".
Lines 520 and 524 are now the idempotency replay return and the
`requires_approval` call.
[`boltrig/kernel/mcp.py:385`](../../../boltrig/kernel/mcp.py) `"same predicate _list_tools uses, because params are validated before"`.

---

RISK: `_record_security` is documented as fail-safe at the chokepoint but has NO
`try/except` at that site. It is called from inside `except BoltrigError`, so if
the injected `security` object's `record` ever raised, the new exception would
MASK the original `GrantMissing` or `RateLimited`. The guarantee is delegated to
`SecurityWriter.record`'s own swallow, which the chokepoint does not enforce on an
arbitrary injected writer.
[`boltrig/kernel/dispatch.py:218`](../../../boltrig/kernel/dispatch.py) `"Fail-safe: no writer wired, or a write error, must"`
against [`boltrig/kernel/dispatch.py:223`](../../../boltrig/kernel/dispatch.py) `"await self._security.record("`.

---

RISK: the `finally` block calls `result_frames(...)` before the audit write, and
that call is NOT inside the try that protects the audit append. `_event_safe`
recurses without a depth bound over an adapter-supplied output, so a pathological
output raising there would skip the audit write entirely and mask the caller's
exception, which is exactly the masquerade the audit guard was written to prevent,
one statement earlier.
[`boltrig/kernel/dispatch.py:435`](../../../boltrig/kernel/dispatch.py) `"for frame in result_frames("`;
[`boltrig/kernel/run_event_projection.py:69`](../../../boltrig/kernel/run_event_projection.py) `"return [_event_safe(item) for item in value]"`.

---

RISK: `routing.py` writes five routing attribution keys into `meta` and states they
exist "so the audit can attribute it ... (SPEC §8 dispatch step 15)". The audit
write reads only `meta["target_adapter"]`. `capability`, `capability_binding_id`,
`connection`, `source_operation` and `route_selected_by` reach nothing. Bounded:
`rg -n "route_selected_by|capability_binding_id" boltrig/ tests/` on the pinned
tree finds only the writes in `routing.py` and the `ExecutionPlan` field itself.
So a routed call's audit row does not record WHICH capability, binding or
connection decided it.
[`boltrig/kernel/routing.py:228`](../../../boltrig/kernel/routing.py) `"so the audit can attribute it - and,"`
against [`boltrig/kernel/dispatch.py:441`](../../../boltrig/kernel/dispatch.py) `"target_adapter = meta.get(\"target_adapter\")"`.

---

RISK: `RateLimit.per` is not validated anywhere and an unrecognised value silently
becomes a 60-second window. A manifest or adapter spec writing `per: "day", max: 1000`
gets 1000 per MINUTE, a 1440x widening, with no error and no log line.
[`boltrig/kernel/ratelimit.py:114`](../../../boltrig/kernel/ratelimit.py) `"window_seconds = _WINDOW_SECONDS.get(rl.per, 60)"`;
`RateLimit` has no `__post_init__` at [`boltrig/models/registry.py:72`](../../../boltrig/models/registry.py) `"class RateLimit:"`.

---

RISK: with `scope: "tenant"` the counter key is the BARE tenant id, so every verb
carrying a tenant-scoped limit shares ONE bucket and whichever call arrives decides
against its own `max`. A chatty low-consequence verb can therefore exhaust the
budget of a high-consequence one, and two verbs with different `max` values on one
tenant produce a limit that depends on arrival order.
[`boltrig/kernel/ratelimit.py:115`](../../../boltrig/kernel/ratelimit.py) `"scope = tenant_id if rl.scope == \"tenant\" else"`.

---

RISK: the rate-limit key is built from the CALLER'S SPELLING (`verb`), while the
limit itself comes from the source operation's binding. With `scope: "verb"`, the
same binding addressed as `crm.contact.create` and as `hubspot.contact.create` gets
TWO independent buckets, so a caller holding both grants can take double the
configured throughput on one destination.
[`boltrig/kernel/dispatch.py:549`](../../../boltrig/kernel/dispatch.py) `"await self._rate.enforce(tenant, verb, binding.rate_limit)"`
with `verb` the caller's name from [`boltrig/kernel/dispatch.py:490`](../../../boltrig/kernel/dispatch.py) `"verb: str,"`.

---

RISK: `_validate` short-circuits on a falsy schema, so a verb registered with
`input_schema={}` is not validated at all and SEC-21's protection is vacuous for
it. Nothing at registration refuses an empty schema.
[`boltrig/kernel/dispatch.py:106`](../../../boltrig/kernel/dispatch.py) `"if not schema:"`;
[`boltrig/kernel/registry.py:159`](../../../boltrig/kernel/registry.py) `"input_schema=spec.input_schema,"` (no emptiness check).

---

RISK: `_require_redeemer` runs BEFORE the request is minted, but `record_held_call`
runs AFTER `PendingHuman` is raised and the request row already exists. A store
fault between the two recreates the exact ground-truth state decision 0018 exists
to prevent: an ANSWERED approval with nothing able to claim it.
[`boltrig/kernel/approval_gate.py:199`](../../../boltrig/kernel/approval_gate.py) `"await _require_redeemer(store, verb, context)"`
then [`boltrig/kernel/dispatch.py:281`](../../../boltrig/kernel/dispatch.py) `"await record_held_call("`.

---

RISK: on the no-manifest boot branch `approval_timeout_seconds` stays None, so
every gate-minted approval is created with `timeout_at = None` and NEVER expires.
SEC-14's timeout half is silently inert on that path.
[`boltrig/api/bootstrap.py:455`](../../../boltrig/api/bootstrap.py) `"kernel = Kernel(store, counter=counter, event_relay=event_relay)"`;
[`boltrig/kernel/hitl.py:147`](../../../boltrig/kernel/hitl.py) `"if timeout_seconds else None"`.

---

RISK: `CredentialResolver.sweep_run_scoped` has no production caller. Bounded:
`rg -n "sweep_run_scoped" boltrig/ tests/ apps/ services/ scripts/ tools/` on the
pinned tree finds the definition, four prose mentions, two gate scripts, and two
direct TEST calls. Its replacement is `held_call.sweep_run_credentials_if_settled`.
Its own docstring admits it is unwired.
[`boltrig/kernel/credentials.py:362`](../../../boltrig/kernel/credentials.py) `"async def sweep_run_scoped(self, tenant_id: str, run_id: str) -> int:"`;
[`boltrig/kernel/held_call.py:295`](../../../boltrig/kernel/held_call.py) `"was never wired anywhere"`.

---

RISK: `CapabilityBinding.input_transform_ref` and `output_transform_ref` are stored,
round-tripped and read back but applied NOWHERE. Doctrine §8 steps 7 and 12
("Transform canonical input into provider input", "Transform and normalise output")
are unimplemented, so a canonical capability call is executed against, and validated
against, the PROVIDER's schema. Bounded:
`rg -n "input_transform_ref|output_transform_ref" boltrig/ tests/` finds only the
model field and the store read/write.
[`boltrig/models/capability_routing.py:144`](../../../boltrig/models/capability_routing.py) `"input_transform_ref: str | None = None"`;
[`docs/SPEC-capability-doctrine.md:627`](../../../docs/SPEC-capability-doctrine.md) `"7. Transform canonical input into provider input."`.

---

RISK: doctrine §8 step 14 ("Issue provenance references") is likewise absent from
dispatch. `entity_provenance` exists as a table but the chokepoint never writes it.
Bounded: `rg -n "provenance" boltrig/kernel/dispatch.py boltrig/kernel/routing.py`
finds one hit, in an unrelated docstring about schema findings.
[`docs/SPEC-capability-doctrine.md:634`](../../../docs/SPEC-capability-doctrine.md) `"14. Issue provenance references."`.

---

RISK: `KernelRegistry.discover` returns each verb's `binding.target_type` and
`binding.target_ref`, which names the concrete adapter behind a verb. The registry
docstring for the same file asserts "The agent never learns which concrete system
sits behind a verb (P4, K-2)".
[`boltrig/kernel/registry.py:355`](../../../boltrig/kernel/registry.py) `"\"target_type\": binding.target_type.value, \"target_ref\": binding.target_ref"`
against [`boltrig/models/registry.py:4`](../../../boltrig/models/registry.py) `"The agent never learns which concrete"`.
Whether this reaches an AGENT depends on which surfaces call `discover`, which is
outside this area's bound.

---

RISK: `GrantChecker.check` returns two DIFFERENT messages for a ceiling denial and
a caller denial, so the refusal text is an oracle telling the caller which layer
said no. The docstring's stated property is narrower ("never returns a reason that
identifies the backend"), so this is not a contradiction, but it is a disclosure
the caller does not need.
[`boltrig/kernel/grants.py:21`](../../../boltrig/kernel/grants.py) `"verb '{verb_id}' is outside the tenant permission ceiling"`
and [`boltrig/kernel/grants.py:23`](../../../boltrig/kernel/grants.py) `"caller is not granted verb '{verb_id}'"`.

---

RISK: `_summarise_params` puts INSTANCE-CHOSEN top-level key names into the
append-only audit row, capped at 50. The module says so plainly and calls it a
recorded LIMIT rather than a safety proof, but it is still caller-supplied text in
a store nothing can unwrite.
[`boltrig/kernel/run_event_projection.py:31`](../../../boltrig/kernel/run_event_projection.py) `"A key NAME is instance-chosen, so no mechanical check can"`.

---

RISK: the one-chokepoint claim itself is not a declared invariant. `P2`,
`US-KER-01` and `K-1` are cited in `dispatch.py`'s first line and none is a key in
`tests/invariants.yaml`; nothing in the gate would fail if a second
`adapter.execute` call site appeared outside the kernel.
[`boltrig/kernel/dispatch.py:1`](../../../boltrig/kernel/dispatch.py) `"The dispatch chokepoint (P2, US-KER-01, K-1)"`.

---

RISK: `boltrig/fleet/browser_executor.py` exposes `POST /v1/execute` which calls an
adapter directly with a `None` credential, guarded only by a fixed header value and
the adapter's own `describe()` verb set, with no grant check, no HITL gate, no rate
limit and no audit row. It is a sidecar behind the kernel-side adapter, but it IS a
network-reachable execute path outside the chokepoint.
[`boltrig/fleet/browser_executor.py:90`](../../../boltrig/fleet/browser_executor.py) `"result = await browser.execute(verb, params, None, context)"`.
