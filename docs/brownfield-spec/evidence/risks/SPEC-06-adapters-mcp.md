# Risks harvested from SPEC-06-adapters-mcp.md

RISK: `HttpAdapter.health()` builds a PLAIN `httpx.AsyncClient` against `self.base_url`
with no egress guard and no IP pinning, unlike every other outbound path in the class,
and `AdapterLoader.refresh_health` calls it on a 30 second background cadence
([`boltrig/adapters/http_base.py:140`](../../../boltrig/adapters/http_base.py)
`"async with httpx.AsyncClient(timeout=min(self.timeout, 5.0)) as client:"`). A
generated adapter's `base_url` comes from the OpenAPI document's `servers[0].url`, so a
spec can steer an unguarded repeated GET at internal space; the response body is
discarded but reachability leaks through the `ok`/`degraded`/`down` value.

---

RISK: the same `health()` silently defeats `setup_without_probe`. The loader seeds
`degraded` at register precisely so a write only credential setup is "deliberately not
an ok provider health claim" ([`boltrig/adapters/loader.py:39`](../../../boltrig/adapters/loader.py)
`"setup posture as degraded; it is deliberately not an \"ok\" provider"`),
but the cloud audio family does not override `health()`, so the first background
refresh flips a reachable provider to `ok`. The binding test only asserts the value at
register time ([`tests/adapters/test_cloud_audio_adapters.py:55`](../../../tests/adapters/test_cloud_audio_adapters.py)
`"assert loader.health_of(\"acme\", adapter.id) == \"degraded\""`).

---

RISK: `docs/extension-contract.md` documents the manifest MCP entry as
`credential: ${LINEAR_MCP_TOKEN}` ([`docs/extension-contract.md:107`](../../../docs/extension-contract.md)
`"credential: ${LINEAR_MCP_TOKEN} # ${ENV}-interpolated, held kernel-side"`),
but `bind_mcp_credential` raises `ControlConflict` on exactly that key
([`boltrig/config/control_mcp.py:70`](../../../boltrig/config/control_mcp.py)
`"'{legacy}' passes raw secret material; use 'credential_ref'"`), and
`_register_consumed_mcp` has no try/except, so following the documented shape ABORTS
boot rather than warning. `manifest.example.yaml:388` has the correct `credential_ref`
form; the two documents disagree.

---

RISK: `local_whisper` and `pocket_voice` pass an explicit
`network_config={"allow_internal": True}` to `HttpAdapter.__init__`
([`boltrig/adapters/builtin/local_whisper.py:122`](../../../boltrig/adapters/builtin/local_whisper.py)
`"network_config={\"allow_internal\": True},"`). Because an explicit config SUPERSEDES
the process default rather than merging with it
([`boltrig/adapters/egress.py:87`](../../../boltrig/adapters/egress.py)
`"ALWAYS superseded by an explicit"`), an operator's
`air_gapped: true`, allow list or block list does NOT bind those two adapters at all.
Their base URLs are env settable (`BOLTRIG_WHISPER_URL`, `POCKET_VOICE_URL`).
[`boltrig/distill/adapter.py:124`](../../../boltrig/distill/adapter.py)
`"assert_egress_allowed(str(client.base_url.join(url)), {\"allow_internal\": True})"`
hardcodes the same waiver per request.

---

RISK: the SEC-61 invariant text states the waiver has exactly ONE governed holder,
`control.mcp_server.register`'s `allow_internal`
([`tests/invariants.yaml:1251`](../../../tests/invariants.yaml)
`"The ONE waiver is explicit and governed"`), which the three adapters above contradict.
They are operator configured rather than agent influenced, so the security property may
still hold, but the invariant's wording no longer describes the code.

---

RISK: `assert_no_metadata_egress` and `is_metadata_ip` have no production caller.
Bounded: `rg -n "assert_no_metadata_egress|is_metadata_ip" --type py` (2026-08-24,
pinned tree) hits only `boltrig/adapters/egress.py` itself and
`tests/security/test_round_sixteen.py`. The function carries a documented fail-open bug
fix and is cited by CLOUD-03, but nothing calls it, so the protection it describes is
actually delivered by `check_network_policy`'s broader `is_blocked_ip`.

---

RISK: `McpConsumerAdapter.connect()` is unreachable in production. Its only production
call site is the `getattr` branch in `activate_adapter_record`
([`boltrig/config/control_operations.py:236`](../../../boltrig/config/control_operations.py)
`"connect = getattr(adapter, \"connect\", None)"`),
which is reached through `control.adapter.activate`, and that verb explicitly REFUSES
an MCP consumer row before getting there
([`boltrig/config/control_plane.py:187`](../../../boltrig/config/control_plane.py)
`"external MCP servers use control.mcp_server lifecycle controls"`).
The MCP activation path instead uses `_probe_once` plus `apply_tool_snapshot`. No other
adapter defines `connect` (bounded: `rg -n "def connect|async def connect" boltrig/`,
2026-08-24, pinned tree). The method's own docstring still asserts that discovery runs at
activation and that `control.adapter.activate` wires it
([`boltrig/adapters/mcp_consumer.py:150`](../../../boltrig/adapters/mcp_consumer.py)
`"Discovery runs at ACTIVATION"`), which is now false. It remains exercised by
[`tests/integration/test_mcp_consumer.py:33`](../../../tests/integration/test_mcp_consumer.py)
`"specs = await consumer.connect()"`.

---

RISK: adapter declared MCP resources are registered ONLY by `Kernel.register_adapter`
([`boltrig/kernel/__init__.py:145`](../../../boltrig/kernel/__init__.py)
`"self.mcp.register_resources("`). Control plane
registration, boot rehydration and `reconcile_*` all call `loader.register` directly, so
any future generated or consumed adapter declaring `mcp_resources` would publish verbs
but no resources, silently. No live impact today.

---

RISK: `mcp_tool_policy.implements_hint` cites `KernelRegistry._declare_capability`
([`boltrig/adapters/mcp_tool_policy.py:65`](../../../boltrig/adapters/mcp_tool_policy.py)
`"``KernelRegistry._declare_capability``): an unapproved mapping"`), but the function is
`declare_capability` in
[`boltrig/kernel/capability_records.py:117`](../../../boltrig/kernel/capability_records.py)
`"async def declare_capability("` and is not a `KernelRegistry` method. A reader
following the citation finds nothing.

---

RISK: the `adapters.runtime` column comment enumerates
`http | sql | mq | file | script` ([`boltrig/store/schema.sql:229`](../../../boltrig/store/schema.sql)
`"runtime TEXT NOT NULL, -- http | sql | mq | file | script"`)
while `McpConsumerAdapter.runtime = "mcp"` is written into it. There is no CHECK
constraint, so rows are accepted, but any consumer reading the comment as the domain is
wrong.

---

RISK: eight test files in `tests/adapters/` bind no invariant (listed in §10),
including the entire MCP pagination bound suite and the entire HTTP egress construction
suite. Deleting them would not move the binding-debt gate.

---

RISK: `HttpAdapter._auth` accepts an arbitrary `headers` dict out of credential material
and copies it onto every request
([`boltrig/adapters/http_base.py:237`](../../../boltrig/adapters/http_base.py)
`"extra = material.get(\"headers\")"`). Material is operator supplied, so this is a
credential store trust boundary rather than an agent one, but it is an unbounded header
injection surface with no key allow list.

---

RISK: `mcp_servers.credential` remains as a nullable legacy column
([`boltrig/store/schema.sql:1372`](../../../boltrig/store/schema.sql) `"credential  TEXT,"`) beside a
schema comment saying it is legacy. Nothing in the read path consults it (bounded:
`rg -n "mcp_servers" boltrig/store/`), but a column named `credential` on a live table
is an attractive nuisance for a future writer.

---

RISK: `mcp_probe_receipts` has no retention or partitioning. Each probe writes a row
keyed by a fresh uuid; a polling operator or a scripted retry loop grows the table
without bound.

---
