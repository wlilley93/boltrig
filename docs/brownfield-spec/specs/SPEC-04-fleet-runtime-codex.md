# SPEC-04: The runtime protocol and the Codex lane

- **area**: 04 The runtime protocol and the Codex lane
- **id-block**: BT-REQ-0400 to BT-REQ-0499
- **referent commit**: `19bcae7fa81663fe8998377c86451ba08fb16e48` (`origin/main`)
- **author-agent**: brownfield-spec area 04
- **date**: 2026-08-24

## Bound of this reading

The Codex subsystem is 11,781 lines across 48 modules under
`boltrig/fleet/infrastructure/codex_*.py`, plus 1,846 lines of runtime selection under
`boltrig/fleet/`, plus 567 lines of `boltrig/api/codex_*.py` and `doctor_codex.py`, plus
595 lines of gate scripts. It is too large to quote exhaustively, so it was read as
follows and every claim below is grounded in a line actually opened:

1. **Every module's top-level definitions were enumerated** (`rg -n "^(class |def |[A-Z_]+ = )"`
   over all 48 `codex_*.py` infrastructure modules plus the 9 fleet-level runtime modules).
2. **Read in full**: `ports/runtime.py`, `runtime.py`, `result.py`, `runtime_resolver.py`,
   `runtime_endpoint_policy.py`, `codex_runtime.py`, `codex_runtime_support.py`,
   `codex_trusted_wall.py`, `codex_kernel_tool_wiring.py`, `codex_kernel_tool_scope.py`,
   `codex_binary_pin.py`, `codex_server_request_handler.py`, `codex_preflight_receipt.py`,
   `codex_runtime_invalidation.py`, `codex_read_only_phase.py`, `codex_kernel_tools_phase.py`,
   `codex_native_collaboration_wire.py`, `api/codex_trusted.py`, `api/codex_execution.py`,
   `api/codex_readiness.py`, `api/doctor_codex.py`, `observability/codex_admission.py`,
   `scripts/check_codex_pin_health.py`, `scripts/check_codex_protocol.py`,
   `docs/CODEX-PRODUCTION-ADMISSION.md`, decisions 0012, 0017, 0020, 0022, 0023
   (`0023-refuse-model-judged-approvals.md`).
3. **Read in depth on the load-bearing ranges**: `codex_agent_runtime.py` (all 437),
   `codex_trusted_proxy_provider.py` (all 675), `codex_runtime_admission.py` (all 373),
   `codex_runtime_config.py` (1-140, 160-399), `codex_runtime_config_toml.py` (1-270),
   `codex_runtime_config_argv.py` (1-135), `codex_cell_policy.py` (1-120, 240-398),
   `codex_cell_supervisor.py` (1-330), `codex_app_server.py` (1-300), `codex_protocol.py`
   (all 350), `codex_runtime_events.py` (1-300), `codex_runtime_actor.py` (1-290),
   `codex_cell_boundary.py` (195-295), `codex_sandbox_engagement.py` (1-60, 140-266),
   `codex_trusted_proxy_ingress.py` (100-300), `codex_stdio_transport.py` (20-70),
   `codex_model_proxy_server.py` (100-200), `model_proxy_tool_ceiling.py` (1-80),
   `permanent_runtime.py` (120-399), `spawn.py` (180-260), `spawn_entrypoints.py` (100-175).
4. **Not read line by line**, and therefore not the subject of any claim here:
   `codex_phase_result_parser.py`, `codex_phase_result_schema.py`,
   `codex_native_subagent_events.py`, `codex_runtime_surface_preflight.py`,
   `codex_runtime_preflight.py` (definitions enumerated only),
   `codex_client_support.py` (definitions enumerated only), the `model_proxy_peer_*`
   attestation family (owned by the cell-identity area), `cell_spawner.py`,
   `cell_slots.py`, `cell_lane.py`, `skill_artifacts.py`, `skill_discovery.py`.
   Where this spec touches those it says so and cites only what was opened.

No test was run. No code was edited. All absence claims below carry their search bound
inline.

## 2. Purpose

This subsystem is the seam between Boltrig's governed orchestration and the process that
actually reasons. It defines two disjoint runtime contracts, a one-shot `Runtime` that a
capability names and a bounded-phase `AgentRuntime` that Codex implements, and it supplies
exactly two implementations of the first: the trusted Codex adapter and a deterministic
non-model `ScriptRuntime`. Every other runtime name that a stored capability or a stale
tenant manifest can still carry resolves to a typed unavailable result that degrades
honestly rather than executing, crashing, or reviving a retired lane.

## 3. Boundaries

**Owns.** The `Runtime` and `AgentRuntime` protocols; runtime construction
(`build_runtime`, `build_trusted_codex_runtime`); the runtime resolver's Codex branch; the
Codex App Server protocol client, event translator, notification actor, cell supervisor,
cell policy, binary pin, config composition, argv pinning, admission, preflight receipts,
kernel-tools lane, per-cell model proxy ceiling, trusted-posture wall; the API composition
factories `build_trusted_codex_config` and `build_codex_execution_stack`; the readiness and
doctor projections of Codex admission; the two pin-health gate scripts.

**Must not touch.** The kernel dispatch chokepoint. `boltrig/kernel/` and `boltrig/models/`
import nothing from `fleet/`
([`AGENTS.md:41`](../../../AGENTS.md) `"Respect the import boundary"`).

**Forbidden imports, and by what rule.** `boltrig/fleet/{domain,ports,application}` may
import only inward layers and the standard library, enforced build-red by
`scripts/check_architecture.py` and bound to `FR-ARC-01`
([`tests/invariants.yaml:59`](../../../tests/invariants.yaml) `"direct imports and common
dynamic-import forms in domain, ports, and application code"`). Two consequences are visible
in this area and are load-bearing:

- The heavy trusted provider is assembled at the API composition boundary, not inside
  `fleet/`, because it needs `httpx` and the `infrastructure` layer
  ([`boltrig/api/codex_trusted.py:5`](../../../boltrig/api/codex_trusted.py) `"imports the fleet"`).
- The Codex execution ledger stack is composed in `boltrig/api/codex_execution.py` for the
  same reason: selecting a store adapter reaches outward
  ([`boltrig/api/codex_execution.py:13`](../../../boltrig/api/codex_execution.py) `"Why this lives in"`).

`boltrig/fleet/runtime.py` deliberately does **not** import `codex_runtime.py` at module
load; the import is inside the `codex` branch of `build_runtime`, and `codex_runtime.py`
guards its own back-import behind `TYPE_CHECKING`
([`boltrig/fleet/codex_runtime.py:29`](../../../boltrig/fleet/codex_runtime.py) `"avoid
importing runtime.py at module load"`).

**Out of scope for this file, named so the reader does not look for it here.** The signed
desktop lane runs its own private local App Server process and is governed by decision 0027;
it stages its own Codex binaries at release time
([`scripts/stage_desktop_codex.py:20`](../../../scripts/stage_desktop_codex.py)
`"VERSION = \"0.144.3\""`) and re-checks a bundled digest natively
([`apps/worker/src-tauri/src/local_agent.rs:31`](../../../apps/worker/src-tauri/src/local_agent.rs)
`"const REQUIRED_RELEASE_CODEX_VERSION"`). The per-cell uid, `SO_PEERCRED` attestation and
model-proxy grant machinery is cited here where the Codex lane depends on it but is
specified by the cell-identity area.

## 4. Objects and contracts

### 4.1 `Runtime`: the one-shot protocol a capability names

```python
class Runtime(Protocol):
    runtime: str
    cost_tier: str
    async def run(self, prompt, context, *, tools: list[str]) -> AgentResult: ...
```

([`boltrig/fleet/runtime.py:23`](../../../boltrig/fleet/runtime.py) `"class Runtime(Protocol):"`,
`:24` `"Implementations are stateless per call."`). It is `@runtime_checkable`
([`boltrig/fleet/runtime.py:22`](../../../boltrig/fleet/runtime.py) `"@runtime_checkable"`).

Three implementations exist in the pinned tree, and no more (bounded:
`rg -n "ScriptRuntime|UnavailableRuntime|build_runtime" -g '!tests' .`, 2026-08-24, pinned tree):

| class | `runtime` | behaviour |
| --- | --- | --- |
| `ScriptRuntime` | `python-script` | deterministic echo of task/tools/actor/depth, `tokens_used=0`, `cost_micros=0` ([`boltrig/fleet/runtime.py:39`](../../../boltrig/fleet/runtime.py) `"runtime = \"python-script\""`) |
| `UnavailableRuntime(ScriptRuntime)` | inherits `python-script` | returns `AgentResult.degrade(runtime=<requested>, reason="runtime_unavailable")` ([`boltrig/fleet/runtime.py:72`](../../../boltrig/fleet/runtime.py) `"reason=\"runtime_unavailable\", prompt=prompt"`) |
| `CodexRuntime` | `codex` | one read-only Codex phase per `run` ([`boltrig/fleet/codex_runtime.py:93`](../../../boltrig/fleet/codex_runtime.py) `"runtime = \"codex\""`) |
| `PermanentAgentRuntime` | the capability's own `runtime` | a wrapper that resolves a pinned runtime per call ([`boltrig/fleet/permanent_runtime.py:140`](../../../boltrig/fleet/permanent_runtime.py) `"self.runtime = capability.runtime"`) |

`UnavailableRuntime` inheriting `ScriptRuntime` is deliberate but subtle: it inherits the
`cost_tier` constructor and the `runtime` attribute (so its `runtime` reads
`"python-script"`, not the requested name), while overriding `run`. The requested name
survives only in the degrade payload.

### 4.2 `AgentResult`: the uniform result every runtime returns

Frozen dataclass, fields `ok`, `output`, `summary`, `tokens_used`, `cost_micros`,
`new_work_items`, `degraded`, `input_tokens`, `output_tokens`
([`boltrig/fleet/result.py:40`](../../../boltrig/fleet/result.py) `"ok: bool"`,
`:58` `"input_tokens: int = 0"`).

Contract points that are load-bearing elsewhere:

- **A degraded run is still `ok=True`.** `degrade()` returns `ok=True, degraded=True` so a
  parent tree keeps running ([`boltrig/fleet/result.py:132`](../../../boltrig/fleet/result.py)
  `"ok=True,"` inside `degrade`). `degraded` is the first-class marker, bound to `US-FLT-07`
  ([`tests/invariants.yaml:465`](../../../tests/invariants.yaml) `"Degraded results are
  first-class"`).
- **The prompt is never embedded in a degrade.** Only `prompt_sha256` and `prompt_bytes`
  ([`boltrig/fleet/result.py:135`](../../../boltrig/fleet/result.py)
  `"\"prompt_sha256\": hashlib.sha256(prompt_bytes).hexdigest()"`).
- **`degrade_reason` is bounded to 200 characters** and carries a runtime tag plus an
  exception CLASS name only ([`boltrig/fleet/result.py:96`](../../../boltrig/fleet/result.py)
  `"return str(reason)[:200] if reason else None"`).
- **A degrade may still be billed.** `tokens_used`, `input_tokens`, `output_tokens` are
  accepted and floored at zero ([`boltrig/fleet/result.py:144`](../../../boltrig/fleet/result.py)
  `"tokens_used=max(0, int(tokens_used or 0))"`).
- **`summary` is an audit line, never the user-facing reply.** `reply_text` reads
  `output["text"]` and falls back to `summary`
  ([`boltrig/fleet/result.py:167`](../../../boltrig/fleet/result.py)
  `"return text or result.get(\"summary\") or \"Done.\""`). The Codex lane sets
  `summary=text[:256]` ([`boltrig/fleet/codex_runtime.py:313`](../../../boltrig/fleet/codex_runtime.py)
  `"summary=text[:256],"`), and using it as the reply once truncated every live chat answer
  at 256 characters ([`tests/invariants.yaml:1382`](../../../tests/invariants.yaml)
  `"every assistant message on a live tenant was exactly 256 chars"`).

### 4.3 `AgentRuntime`: the bounded-phase lifecycle port

```python
class AgentRuntime(Protocol):
    name: str
    async def start_thread(spec: RuntimeThreadSpec) -> RuntimeThreadRef
    async def resume_thread(thread) -> RuntimeThreadRef
    async def start_turn(spec: RuntimeTurnSpec) -> RuntimeTurnRef
    async def steer_turn(request: TurnSteerRequest) -> RuntimeTurnRef
    async def interrupt_turn(turn) -> None
    def events(thread) -> AsyncIterator[RuntimeEvent]
    async def close_thread(thread) -> None
```

([`boltrig/fleet/ports/runtime.py:54`](../../../boltrig/fleet/ports/runtime.py)
`"class AgentRuntime(Protocol):"`, methods at `:59` to `:70`).

The three input values:

| value | fields | defaults |
| --- | --- | --- |
| `RuntimeThreadSpec` | `assignment`, `profile`, `skills`, `working_directory`, `mode`, `sandbox`, `metadata` | `mode=PhaseMode.READ_ONLY`, `sandbox=SandboxPolicy.READ_ONLY` ([`boltrig/fleet/ports/runtime.py:30`](../../../boltrig/fleet/ports/runtime.py) `"mode: PhaseMode = PhaseMode.READ_ONLY"`) |
| `RuntimeTurnSpec` | `thread`, `prompt`, `client_message_id`, `output_schema` | `output_schema=None`; the docstring pins the rule ([`boltrig/fleet/ports/runtime.py:37`](../../../boltrig/fleet/ports/runtime.py) `"policy remains outside the prompt"`) |
| `TurnSteerRequest` | `turn`, `prompt`, `client_message_id` | tied to the expected active turn ([`boltrig/fleet/ports/runtime.py:47`](../../../boltrig/fleet/ports/runtime.py) `"Additional input tied to the expected active turn."`) |

The two protocols are **disjoint by design**. `CodexRuntime` is the bridge: it mints a
read-only assignment, runs exactly one turn, reads the assistant text back, and returns an
`AgentResult` ([`boltrig/fleet/codex_runtime.py:8`](../../../boltrig/fleet/codex_runtime.py)
`"bridges the two: it mints a"`).

`events()` is a **content-free lifecycle ledger**. The turn's actual text is captured
inside the event translator and read back through a separate method, because the App
Server's headless exec mode answers `-32600` to `thread/read`
([`boltrig/fleet/infrastructure/codex_agent_runtime.py:291`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
`"App Server's headless exec mode does not serve"`).

### 4.4 `CodexAgentRuntime`: the App Server implementation

- `name = "codex_app_server"`, `production_ready = False`
  ([`boltrig/fleet/infrastructure/codex_agent_runtime.py:60`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
  `"name = \"codex_app_server\""`, `:59` `"production_ready = False"`).
- The constructor **refuses to build** unless `allow_test_only_runtime=True`
  ([`:70`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
  `"Codex runtime requires unresolved production isolation controls"`).
- Bounds: `MAX_ACTIVE_CODEX_PHASES = 64`, `max_buffered_events` 1 to 256, root start timeout
  0 to 30 seconds ([`:49`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
  `"MAX_ACTIVE_CODEX_PHASES = 64"`, `:83` `"not 0 < root_timeout <= 30"`).
- **One owner per phase**: a second `start_thread` for the same phase key is refused
  ([`:335`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
  `"phase already has a Codex owner"`).
- Terminal states are typed by category, `protocol` / `binding` / `closed` / `operation`,
  and mapped back to exceptions at the boundary
  ([`:422`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
  `"def _terminal_exception(terminal"`).

### 4.5 Cell objects

| object | what it is | key invariants |
| --- | --- | --- |
| `CodexCellLayout` | pre-provisioned paths for one cell | admission seam, "the supervisor never creates, projects, copies, or trusts any of these paths" ([`boltrig/fleet/infrastructure/codex_cell_policy.py:44`](../../../boltrig/fleet/infrastructure/codex_cell_policy.py) `"creates, projects, copies, or trusts any of these paths."`) |
| `PinnedCodexBinary` | one held, verified executable descriptor | executes via `/proc/self/fd/<n>`, pathname is audit-only ([`boltrig/fleet/infrastructure/codex_binary_pin.py:57`](../../../boltrig/fleet/infrastructure/codex_binary_pin.py) `"return f\"/proc/self/fd/{self.fileno()}\""`) |
| `CodexUpstreamAuth` | supervisor-managed upstream secret | `__repr__` redacts, `__reduce__` raises ([`boltrig/fleet/infrastructure/codex_cell_policy.py:94`](../../../boltrig/fleet/infrastructure/codex_cell_policy.py) `"upstream Codex auth cannot be serialized"`) |
| `CodexPhaseAdmission` | pre-provisioned cell plus immutable birth policy | read-only sandbox, no enabled tools, zero native limits ([`boltrig/fleet/infrastructure/codex_runtime_admission.py:129`](../../../boltrig/fleet/infrastructure/codex_runtime_admission.py) `"Codex runtime admission is read-only"`) |
| `AdmittedCodexCell` | admission + initialized cell + preflight receipt | binds observed MCP count to the admitted lane ([`boltrig/fleet/infrastructure/codex_runtime_admission.py:165`](../../../boltrig/fleet/infrastructure/codex_runtime_admission.py) `"observed MCP inventory does not match the admitted lane"`) |
| `QuarantinedCodexPreflightReceipt` | the only implemented pre-thread evidence | `production_complete` is a constant `False` ([`boltrig/fleet/infrastructure/codex_preflight_receipt.py:75`](../../../boltrig/fleet/infrastructure/codex_preflight_receipt.py) `"return False"`) |
| `CodexRuntimeConfigReceipt` | composition metadata for the cell's `config.toml` | `production_ready` must be `False`, argv is derived not stored ([`boltrig/fleet/infrastructure/codex_runtime_config.py:202`](../../../boltrig/fleet/infrastructure/codex_runtime_config.py) `"Deliberately NOT a stored field."`) |
| `CodexKernelToolScope` | one assignment's MCP url, tool ceiling and run token | `__repr__` redacts, `__reduce_ex__` raises ([`boltrig/fleet/infrastructure/codex_kernel_tool_scope.py:76`](../../../boltrig/fleet/infrastructure/codex_kernel_tool_scope.py) `"kernel tool scopes must not be pickled or copied"`) |
| `CodexKernelToolWiring` | injected non-secret seams for the tools lane | TTL bounded 1 to 3600 seconds ([`boltrig/fleet/codex_kernel_tool_wiring.py:44`](../../../boltrig/fleet/codex_kernel_tool_wiring.py) `"not 1 <= self.ttl_seconds <= 3600"`) |

### 4.6 Lifecycles

**Runtime object lifecycle.** A `Runtime` is built per resolution and is stateless per call
([`boltrig/fleet/runtime.py:24`](../../../boltrig/fleet/runtime.py) `"Implementations are
stateless per call."`). The resolver builds a fresh one for every spawn
([`boltrig/fleet/spawn.py:194`](../../../boltrig/fleet/spawn.py)
`"return await self._runtime_resolver.runtime_for("`).

**Codex phase lifecycle.** `acquire` (provider) -> `start_thread` -> `start_turn` ->
`events` drained to `turn/completed` -> `read_turn_output` -> `close_thread`, with cell
teardown, bearer revocation and slot release driven by a reaper task
([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:628`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
`"async def _reap("`).

**Kernel-tools scope lifecycle.** Registered by the adapter before the phase, popped once by
the provider, discarded in the adapter's `finally`, and the token revoked in the same
`finally` ([`boltrig/fleet/codex_runtime.py:233`](../../../boltrig/fleet/codex_runtime.py)
`"wiring.registry.discard(assignment.assignment_id)"`).

## 5. Control flow

### 5.1 Selecting a runtime for one spawn

1. **Caller composes the prompt and hands it to the resolver as the egress payload**, so the
   PII scanner classifies before the destination is chosen
   ([`boltrig/fleet/spawn.py:240`](../../../boltrig/fleet/spawn.py)
   `"outbound_text=self._compose_prompt(merged_prompt, task),"`).
   *Failure branch*: any exception in resolution settles the child subagent node as errored
   and refunds the whole budget reservation
   ([`boltrig/fleet/spawn.py:255`](../../../boltrig/fleet/spawn.py)
   `"self._publish_subagent_end_event(context, run_id, \"error\")"`).
2. **`RuntimeResolver.runtime_for` resolves the base model** through `resolve_base_model`
   ([`boltrig/fleet/runtime_resolver.py:125`](../../../boltrig/fleet/runtime_resolver.py)
   `") = await resolve_base_model("`).
   *Failure branch*: under a production signal a missing execution context, a failed AI-key
   resolution, or a default (unscoped) credential each raise `CredentialResolution`
   ([`boltrig/fleet/runtime_resolver.py:307`](../../../boltrig/fleet/runtime_resolver.py)
   `"production runtime requires an authenticated execution context"`, `:329`
   `"production AI execution requires a scoped credential reference"`). Off production the
   same conditions return `(None, None)` and the resolution continues.
3. **If the capability is `codex` and the request is not sensitive**, a Codex endpoint is
   resolved ([`boltrig/fleet/runtime_resolver.py:137`](../../../boltrig/fleet/runtime_resolver.py)
   `"if capability.runtime == \"codex\" and not sensitive:"`). A configured non-default AI
   key with no explicit endpoint choice routes through a scoped Bifrost binding
   ([`boltrig/fleet/runtime_resolver.py:183`](../../../boltrig/fleet/runtime_resolver.py)
   `"return await self._scoped_default_endpoint("`).
   *Failure branch*: `BifrostUserBindingUnavailable` becomes `ModelEndpointUnavailable`
   ([`boltrig/fleet/runtime_resolver.py:221`](../../../boltrig/fleet/runtime_resolver.py)
   `"the configured AI provider is not ready"`).
4. **The conversation gateway is applied** so a conversation stays bound to one route
   ([`boltrig/fleet/runtime_endpoint_policy.py:35`](../../../boltrig/fleet/runtime_endpoint_policy.py)
   `"return apply_gateway("`).
5. **Under `pinned_policy`, the composed Codex model must equal the resolved endpoint model**,
   else `PinnedRuntimePolicyUnavailable`
   ([`boltrig/fleet/runtime_resolver.py:250`](../../../boltrig/fleet/runtime_resolver.py)
   `"the composed Codex model does not satisfy the pinned profile"`). This is what stops a
   user's provider choice silently replacing an authored permanent Codex head.
6. **`_codex_config` builds the injected marker**, gated only on `capability.runtime ==
   "codex"` and on a provider having been injected
   ([`boltrig/fleet/runtime_resolver.py:359`](../../../boltrig/fleet/runtime_resolver.py)
   `"if capability.runtime != \"codex\":"`). It sets `kernel_tools` when
   `allow_kernel_tools` and either `force_kernel_tools` or `"*" in supported_skills`
   ([`boltrig/fleet/runtime_resolver.py:368`](../../../boltrig/fleet/runtime_resolver.py)
   `"cfg[\"kernel_tools\"] = allow_kernel_tools and ("`), and carries `issue_token`,
   `revoke_token`, `mcp_url` and `compile_tool_ceiling`.
7. **`build_runtime` dispatches on the capability name** ([`boltrig/fleet/runtime.py:91`](../../../boltrig/fleet/runtime.py)
   `"if kind == \"codex\":"`, `:95` `"if kind in {\"script\", \"python-script\",
   \"go-binary\"}:"`, `:97` `"return UnavailableRuntime(requested=kind"`). `endpoint_lookup`
   is accepted for call-shape compatibility and discarded
   ([`boltrig/fleet/runtime.py:89`](../../../boltrig/fleet/runtime.py) `"del endpoint_lookup"`).
8. **A resolved model route is attached to the runtime object** for cost and provenance
   ([`boltrig/fleet/runtime_resolver.py:298`](../../../boltrig/fleet/runtime_resolver.py)
   `"setattr(runtime, \"model_route\", model_route)"`). An unavailable runtime gets no
   speculative model label (the `model_route is None` path at `:296`).

### 5.2 Constructing the trusted Codex runtime

1. `build_trusted_codex_runtime` requires `trusted`, a provider, a stack root and a
   non-empty `model_id` string; anything short of that returns `UnavailableRuntime`
   ([`boltrig/fleet/codex_runtime.py:343`](../../../boltrig/fleet/codex_runtime.py) `"if not ("` through
   `:350` `"return UnavailableRuntime(requested=\"codex\""`).
2. `require_codex_trusted_posture()` is re-asserted here even though the composition root
   already gated the flag ([`boltrig/fleet/codex_runtime.py:357`](../../../boltrig/fleet/codex_runtime.py)
   `"require_codex_trusted_posture()"`).
   *Failure branch*: raises `CodexTrustedPostureError`, which propagates out of
   `build_runtime` to the caller; at the permanent seam it is caught and turned into a typed
   degrade ([`boltrig/fleet/permanent_runtime.py:288`](../../../boltrig/fleet/permanent_runtime.py)
   `"result, cost_micros = await self._runtime_unavailable("`).
3. The provider's **exact type** is checked, not its protocol conformance
   ([`boltrig/fleet/codex_runtime.py:358`](../../../boltrig/fleet/codex_runtime.py)
   `"if type(provider) is not TrustedProxyCodexPhaseCellProvider:"`).
4. When `kernel_tools` is set, `CodexKernelToolWiring` is constructed; a `TypeError` or
   `ValueError` from its validation yields `UnavailableRuntime`, never a silent downgrade to
   read-only reasoning ([`boltrig/fleet/codex_runtime.py:373`](../../../boltrig/fleet/codex_runtime.py)
   `"except (TypeError, ValueError):"`).
5. `CodexAgentRuntime(provider, allow_test_only_runtime=True)` is the only constructor path
   used ([`boltrig/fleet/codex_runtime.py:376`](../../../boltrig/fleet/codex_runtime.py)
   `"CodexAgentRuntime(provider, allow_test_only_runtime=True),"`).

### 5.3 One Codex turn (`CodexRuntime.run`)

1. **Scope check.** No `run_id` or no `workspace_id` degrades with
   `no_read_only_phase_scope` ([`boltrig/fleet/codex_runtime.py:138`](../../../boltrig/fleet/codex_runtime.py)
   `"reason=\"no_read_only_phase_scope\", prompt=prompt"`).
2. **Assignment mint.** Deterministic: `phase_id = f"{run_id}-codex"`, `assignment_id =
   f"{run_id}-codex-assignment"`
   ([`boltrig/fleet/codex_runtime_support.py:168`](../../../boltrig/fleet/codex_runtime_support.py)
   `"phase_id=f\"{run_id}-codex\","`).
3. **Model binding registration.** Registered when a binding registry is present; a failure
   degrades with `codex_model_binding_failed:<ExcClass>`
   ([`boltrig/fleet/codex_runtime.py:159`](../../../boltrig/fleet/codex_runtime.py)
   `"reason=f\"codex_model_binding_failed:{type(error).__name__}\","`) and is discarded in
   `finally` ([`boltrig/fleet/codex_runtime.py:171`](../../../boltrig/fleet/codex_runtime.py)
   `"self._model_bindings.discard(assignment)"`).
4. **Lane selection.** With `kernel_tools` wiring present, the tools lane; otherwise the
   read-only lane ([`boltrig/fleet/codex_runtime.py:163`](../../../boltrig/fleet/codex_runtime.py)
   `"if self._kernel_tools is not None:"`).
5. **Tools lane, step by step**:
   a. compile the ceiling: `tenant permissions ∩ run grants` through `offer_candidates`
      ([`boltrig/fleet/runtime_resolver.py:392`](../../../boltrig/fleet/runtime_resolver.py)
      `"candidates = await offer_candidates("`);
   b. map verb ids to Codex wire names; `None` means inadmissible and the caller runs the
      read-only phase instead, which is logged with its reason
      ([`boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:194`](../../../boltrig/fleet/infrastructure/codex_kernel_tools_phase.py)
      `"falling back to the read-only phase"`);
   c. issue a run-scoped kernel MCP token with the run's grants, actor, skills, workspace and
      `parent_run_id` ([`boltrig/fleet/codex_runtime.py:196`](../../../boltrig/fleet/codex_runtime.py)
      `"token = wiring.issue_token("`);
   d. register a `CodexKernelToolScope` in the pop-once registry
      ([`boltrig/fleet/codex_runtime.py:212`](../../../boltrig/fleet/codex_runtime.py)
      `"wiring.registry.register("`);
   e. run the phase with `kernel_tools_thread_spec`.
   *Failure branch*: any exception degrades with `codex_turn_failed:<ExcClass>` and never
   raises into the caller ([`boltrig/fleet/codex_runtime.py:229`](../../../boltrig/fleet/codex_runtime.py)
   `"reason=f\"codex_turn_failed:{type(error).__name__}\","`). The `finally` always discards
   the scope and revokes the token under `contextlib.suppress(Exception)`
   ([`boltrig/fleet/codex_runtime.py:235`](../../../boltrig/fleet/codex_runtime.py)
   `"with contextlib.suppress(Exception):"`).
6. **`_run_phase`**: `start_thread`, `start_turn` with a fresh `uuid4().hex` client message
   id, `drain_until_complete`, `read_turn_output`
   ([`boltrig/fleet/codex_runtime.py:254`](../../../boltrig/fleet/codex_runtime.py)
   `"thread = await self._lifecycle.start_thread(spec)"`).
   *Failure branches, in order of the except clauses*:
   - `ToolBudgetExhausted`: the turn is interrupted (suppressing failure), and a
     `codex_tool_budget_exhausted:<n>` degrade carries the spend
     ([`boltrig/fleet/codex_runtime.py:267`](../../../boltrig/fleet/codex_runtime.py)
     `"await self._lifecycle.interrupt_turn(turn)"`);
   - any other `Exception`: full traceback logged, degrade tagged with the exception class,
     spend from the last observed usage report
     ([`boltrig/fleet/codex_runtime.py:286`](../../../boltrig/fleet/codex_runtime.py)
     `"tokens_used=usage_seen[-1] if usage_seen else 0,"`);
   - `finally`: `close_thread` under `contextlib.suppress(Exception)`
     ([`boltrig/fleet/codex_runtime.py:293`](../../../boltrig/fleet/codex_runtime.py)
     `"await self._lifecycle.close_thread(thread)"`);
   - empty text after a clean drain: `codex_empty_output` or
     `codex_empty_output_after_error`, still billed
     ([`boltrig/fleet/codex_runtime_support.py:36`](../../../boltrig/fleet/codex_runtime_support.py)
     `"return \"codex_empty_output_after_error\""`).
7. **Success.** `output={"runtime": "codex_app_server", "text": text}`, `summary=text[:256]`,
   usage split reported, `cost_micros` left to the accountant
   ([`boltrig/fleet/codex_runtime.py:311`](../../../boltrig/fleet/codex_runtime.py)
   `"return AgentResult.succeeded("`).

### 5.4 Draining the event stream

`drain_until_complete` walks the async iterator and:

- counts `ITEM_STARTED` events whose `item_type` is in `TOOL_ITEM_TYPES` (7 types) and raises
  `ToolBudgetExhausted` on the step **after** the budget
  ([`boltrig/fleet/codex_runtime_support.py:113`](../../../boltrig/fleet/codex_runtime_support.py)
  `"if tool_steps > max_tool_steps:"`);
- accumulates `ERROR` payloads into a caller-owned list so a raise does not lose them
  ([`boltrig/fleet/codex_runtime_support.py:117`](../../../boltrig/fleet/codex_runtime_support.py)
  `"errors.append(event.payload.to_mapping())"`);
- takes the **last** `TOKEN_USAGE` report before completion, requiring `type(reported) is int
  and reported > 0` ([`boltrig/fleet/codex_runtime_support.py:121`](../../../boltrig/fleet/codex_runtime_support.py)
  `"if type(reported) is int and reported > 0:"`);
- returns on `TURN_COMPLETED` ([`boltrig/fleet/codex_runtime_support.py:129`](../../../boltrig/fleet/codex_runtime_support.py)
  `"return tokens"`).

### 5.5 Acquiring a cell (`TrustedProxyCodexPhaseCellProvider.acquire`)

1. `require_codex_trusted_posture(self._env, self._settings)` before anything is provisioned
   ([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:244`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"require_codex_trusted_posture(self._env, self._settings)"`).
2. If `config.toml` is not protected by the boundary, take the admission lock and refuse a
   second live cell ([`:250`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"self._require_admissible_concurrency()"`, `:542` `"if self._sessions and not
   self._boundary.config_toml_protected:"`).
3. Take the assignment's model binding; absence or a tenant mismatch fails closed
   ([`:325`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"trusted Codex assignment has no resolved model binding"`).
4. Pop the kernel-tools scope (pop-once) to choose the lane
   ([`:273`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"kernel_scope = self._kernel_tool_scopes.take(assignment.assignment_id)"`). An empty
   ceiling on the tools lane is a programming error and fails closed
   ([`:466`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"kernel tool scope does not match the assignment"`).
5. Acquire a cell slot, admit, start the per-cell loopback model proxy, select a random
   abstract ingress socket name, compose and write `config.toml`, derive the pinned argv.
6. Spawn under the supervisor with `on_spawned` running the registration against the
   just-spawned pid, before any protocol traffic
   ([`:307`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"cell = await self._supervisor.start("`; the contract at `:301` `"before any protocol
   traffic, so there is no instant in which a live"`).
7. Probe the lane's preflight, construct `AdmittedCodexCell`, register the session with a
   reaper task.
   *Failure branch*: `_abort_acquire` tears down proxy, scope, ingress, closes the cell,
   removes an API-owned cell tree, and releases the slot only if the reaper has not taken
   ownership ([`:428`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"await self._teardown(proxy, scope, ingress)"`).

### 5.6 Answering a Codex server-initiated request

1. Only `item/tool/requestUserInput` is handled; every other method is refused with
   `-32601` ([`boltrig/fleet/infrastructure/codex_server_request_handler.py:70`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py)
   `"return _error(request.request_id, _METHOD_NOT_FOUND"`).
2. Every question is answered with the **approve** option that Codex itself offered, matched
   case-insensitively against a fixed label set
   ([`:52`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py)
   `"_APPROVE_LABELS = frozenset("`).
3. Zero or more than one candidate approve label is **refused with `-32602`**, never a
   fabricated label and never an auto-deny
   ([`:116`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py)
   `"if len({label.strip().lower() for label in matches}) != 1:"`).
4. The handler makes **no gating decision of its own**: the kernel `/v1/mcp` door is the sole
   governing locus ([`:17`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py)
   `"This handler makes NO gating decision of its own"`), bound by `CODEX-APPROVAL-2`
   ([`tests/invariants.yaml:44`](../../../tests/invariants.yaml) `"it never inspects the"`).

## 6. Data

This subsystem writes **no database tables of its own on the live path**. Its durable
surfaces are:

| surface | where | state |
| --- | --- | --- |
| `RootEngineDecision` rows | `PostgresRootEngineDecisionStore` selected in `build_codex_execution_stack` ([`boltrig/api/codex_execution.py:154`](../../../boltrig/api/codex_execution.py) `"decisions = PostgresRootEngineDecisionStore(pool)"`) | written only when `BOLTRIG_CODEX_LEDGER` is on; one insert-once decision per root run |
| execution ledger | `PostgresExecutionLedger` ([`boltrig/api/codex_execution.py:155`](../../../boltrig/api/codex_execution.py) `"ledger = PostgresExecutionLedger(pool)"`) | constructed behind the flag; `AssignmentAdmission.admit` is never called (bounded: `rg -n "assignment_admission\|\.admit\(" boltrig/`, 2026-08-24, pinned tree) |
| capability attestations | `PostgresCapabilityAttestationStore` ([`boltrig/api/codex_execution.py:156`](../../../boltrig/api/codex_execution.py) `"attestations = PostgresCapabilityAttestationStore(pool)"`) | same, unexercised |
| model-proxy grants | `MemoryModelProxyGrantStore` in the trusted composition ([`boltrig/api/codex_trusted.py:199`](../../../boltrig/api/codex_trusted.py) `"grant_store = MemoryModelProxyGrantStore()"`) | in-memory only in this composition; the durable Postgres adapter exists but is not wired here |
| audit rows | the permanent seam writes `ActionType.MODEL_CALL` with capability, runtime, tier, model route and degrade reason ([`boltrig/fleet/permanent_runtime.py:379`](../../../boltrig/fleet/permanent_runtime.py) `"action_type=ActionType.MODEL_CALL,"`) | live |

**Checked-in data**, and it is a security artefact rather than convenience data:

- `schemas/codex/0.144.3/manifest.json` and
  `schemas/codex/0.144.3/codex_app_server_protocol.v2.schemas.json`. Two files exactly
  (bounded: `find schemas/codex -type f | wc -l` = 2, 2026-08-24, pinned tree). The manifest
  pins version, target, binary sha256, `experimentalApi: false`, an exact two-entry transport
  allowlist and `remoteWebSocketAllowed: false`, plus the canonical stable-v2 root digest and
  a 267-file bundle probe ([`schemas/codex/0.144.3/manifest.json:15`](../../../schemas/codex/0.144.3/manifest.json)
  `"\"remoteWebSocketAllowed\": false"`).

**Retention and redaction.** No prompt, model output, tool argument or peer payload is
persisted by this subsystem. The disciplines that make that true:

- `AgentResult.degrade` stores only a prompt digest and byte length
  ([`boltrig/fleet/result.py:135`](../../../boltrig/fleet/result.py) `"\"prompt_sha256\""`);
- protocol errors never include payloads
  ([`boltrig/fleet/infrastructure/codex_protocol.py:17`](../../../boltrig/fleet/infrastructure/codex_protocol.py)
  `"Base error whose text never includes request or response payloads."`);
- unknown notification methods are reported as a **digest of the method name**
  ([`boltrig/fleet/infrastructure/codex_runtime_events.py:165`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py)
  `"payload={\"method_digest\": _method_digest(notification.method)},"`);
- cell stderr is classified against a 7-token allowlist and only the stable LABELS surface
  ([`boltrig/fleet/infrastructure/codex_stdio_transport.py:51`](../../../boltrig/fleet/infrastructure/codex_stdio_transport.py)
  `"def classify_codex_stderr(tail: bytes)"`);
- the pump crash log carries the exception class only, never `exc_info` or `str(exc)`
  ([`boltrig/fleet/infrastructure/codex_runtime_actor.py:273`](../../../boltrig/fleet/infrastructure/codex_runtime_actor.py)
  `"NOT exc_info and NOT str(exc)"`).

**Encryption.** None applied here. The cell's bearer never rests on disk: it is written to an
`SO_PEERCRED`-attested socket connection and no bearer file exists
([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:16`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
`"the bearer is written to the"` / `"SO_PEERCRED-attested socket connection and NO bearer
file exists"`).

## 7. Configuration surface

| key | default | read at | what breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_CODEX_TRUSTED` | unset (off) | [`boltrig/config/settings.py:118`](../../../boltrig/config/settings.py) `"codex_trusted=_as_bool(e.get(\"BOLTRIG_CODEX_TRUSTED\"))"` | off means `build_trusted_codex_config` returns `None`, `_codex_config` returns `None`, and every `runtime: codex` capability degrades to `UnavailableRuntime`. On with a production signal, the wall raises. |
| `BOLTRIG_CODEX_BINARY` | unset | [`boltrig/config/settings.py:119`](../../../boltrig/config/settings.py) `"codex_binary=e.get(\"BOLTRIG_CODEX_BINARY\") or None"` | absent means no provider is constructed; present but wrong-digest, group-writable or missing makes `make codex-pin-health` FATAL and every cell spawn fail at `verify_pinned_binary`. |
| `BOLTRIG_CODEX_STACK_ROOT` | unset | [`boltrig/config/settings.py:120`](../../../boltrig/config/settings.py) `"codex_stack_root=e.get(\"BOLTRIG_CODEX_STACK_ROOT\")"` | absent means no provider. Present but not writable makes the sandbox-engagement probe fail closed at composition. |
| `BOLTRIG_CODEX_MODEL` | `"glm-4.6"` | [`boltrig/config/settings.py:121`](../../../boltrig/config/settings.py) `"codex_model=(e.get(\"BOLTRIG_CODEX_MODEL\") or \"glm-4.6\")"` | the model the read-only cell pins; a mismatch against a pinned permanent profile raises `PinnedRuntimePolicyUnavailable`. |
| `BOLTRIG_CODEX_LEDGER` | unset (off) | [`boltrig/config/settings.py:117`](../../../boltrig/config/settings.py) `"codex_ledger=_as_bool(e.get(\"BOLTRIG_CODEX_LEDGER\"))"` | off means the execution stack is never constructed and `app.state.platform` carries `None`. On adds one execution-neutral shadow decision per root run. |
| `BOLTRIG_CODEX_MAX_TOOL_STEPS` | 16 | [`boltrig/fleet/codex_runtime_support.py:62`](../../../boltrig/fleet/codex_runtime_support.py) `"_MAX_TOOL_STEPS_ENV = \"BOLTRIG_CODEX_MAX_TOOL_STEPS\""` | `0` disables the cap entirely (an operator decision, not a fallback); an unparsable value keeps 16 rather than silently uncapping; a negative value also keeps 16. |
| `BOLTRIG_CODEX_MCP_URL`, else `BOLTRIG_MCP_URL` | `http://kernel:8000/v1/mcp` | [`boltrig/fleet/runtime_resolver.py:374`](../../../boltrig/fleet/runtime_resolver.py) `"os.environ.get(\"BOLTRIG_CODEX_MCP_URL\")"` | wrong value points the kernel-tools cell at the wrong MCP face; it is validated by `validate_mcp_server_url` at wiring construction and a bad value yields `UnavailableRuntime`. |
| `BOLTRIG_CODEX_AUTH_HELPER` | `/opt/boltrig/codex/model_auth_helper` | [`boltrig/fleet/infrastructure/codex_cell_boundary.py:64`](../../../boltrig/fleet/infrastructure/codex_cell_boundary.py) `"SHARED_HELPER_ENV_KEY = \"BOLTRIG_CODEX_AUTH_HELPER\""` | pointing it at a path this account can write, or inside the mutable stack root, refuses provider construction at composition. |
| `BOLTRIG_CODEX_MCP_RUN_TOKEN` | not an operator key | [`boltrig/fleet/infrastructure/codex_runtime_config_toml.py:23`](../../../boltrig/fleet/infrastructure/codex_runtime_config_toml.py) `"CODEX_MCP_BEARER_ENV_VAR = \"BOLTRIG_CODEX_MCP_RUN_TOKEN\""` | the child-process delivery channel for the run-scoped kernel token. It is the only environment addition the cell receives. |
| `BOLTRIG_DEV_AUTH` | unset | [`boltrig/config/settings.py:116`](../../../boltrig/config/settings.py) `"dev_auth=_as_bool(e.get(\"BOLTRIG_DEV_AUTH\"))"` | selects trusted-posture (a). Combined with a real ingress posture it no longer qualifies. |
| `BOLTRIG_AUTH_MODE`, `OIDC_*`, `CF_ACCESS_*` | unset | [`boltrig/config/settings.py:90`](../../../boltrig/config/settings.py) `"def oidc_configured"` and neighbours | any of these being configured is a "real ingress posture"; without per-cell uids that combination is refused by the wall. |
| `BOLTRIG_RELEASE_MODE` | see `release_mode.py` | [`boltrig/api/codex_readiness.py:40`](../../../boltrig/api/codex_readiness.py) `"mode = configured_release_mode(env)"` | `core` plus an enabled trusted flag is a hard `release_mode_conflict` failure in readiness and doctor. |
| `BOLTRIG_CELL_SPAWNER_FD` | unset | [`boltrig/api/codex_trusted.py:55`](../../../boltrig/api/codex_trusted.py) `"\"cell_lane\": bool(os.environ.get(\"BOLTRIG_CELL_SPAWNER_FD\"))"` | its presence (validated as a live unix socket) is how posture (b) is detected; it is never asserted by configuration alone. |
| manifest `runtimes.<kind>.enabled` | absent | [`boltrig/api/doctor.py:352`](../../../boltrig/api/doctor.py) `"for kind in _RETIRED_RUNTIMES:"` | a manifest enabling a retired name produces a doctor `warn`, never a deploy block, because such a capability degrades. |
| manifest capability `runtime:` | `codex` for every shipped lane | [`manifest.example.yaml:138`](../../../manifest.example.yaml) `"runtime: codex"` | naming anything other than `codex`, `script`, `python-script` or `go-binary` yields a typed unavailable result. |
| `default_runtime` | `codex-worker` | [`manifest.example.yaml:484`](../../../manifest.example.yaml) `"default_runtime: codex-worker"` | names a CAPABILITY, not a runtime; that capability resolves to `runtime: codex`. |

Note that `adapters[].runtime` in the manifest (`http`, `sql`, `script`) is a **different
namespace**: it selects an adapter implementation, not a fleet `Runtime`
([`manifest.example.yaml:238`](../../../manifest.example.yaml) `"- id: ms-graph"`, whose
`runtime: http` on the next line sits under `adapters:`). Passing one of those strings to
`build_runtime` would produce `UnavailableRuntime`, but nothing does (bounded:
`rg -n "build_runtime" -g '!tests' .`, 2026-08-24, pinned tree, one call site:
[`boltrig/fleet/runtime_resolver.py:268`](../../../boltrig/fleet/runtime_resolver.py)
`"return build_runtime("`).

## 8. PROCESS

### 8.1 Bringing the lane up on a development box

The only lawful posture for a live Codex cell today is a development one. The
documented preconditions are:

1. `BOLTRIG_DEV_AUTH=1`, no real ingress posture, no production or staging signal
   ([`docs/CODEX-PRODUCTION-ADMISSION.md:191`](../../../docs/CODEX-PRODUCTION-ADMISSION.md)
   `"A local single-operator development release is viable now with"`), **or** a deployment
   that enacts per-cell uids, under which session login may coexist
   ([`docs/decisions/0017-trusted-codex-postures.md:35`](../../../docs/decisions/0017-trusted-codex-postures.md)
   `"(b) Kernel-attested posture"`).
2. `BOLTRIG_CODEX_TRUSTED=1`, `BOLTRIG_CODEX_BINARY` pointing at the pinned artefact, and
   `BOLTRIG_CODEX_STACK_ROOT` at a writable per-cell layout root.
3. The shared root-owned auth helper installed on a read-only mount, and host
   `kernel.yama.ptrace_scope >= 1` (not namespaced, so it is a host precondition the
   container can only assert, never create)
   ([`boltrig/fleet/infrastructure/codex_cell_boundary.py:205`](../../../boltrig/fleet/infrastructure/codex_cell_boundary.py)
   `"This sysctl is NOT namespaced: a"`).

Composition then proves, in this order, before any provider object exists:

- the read-only sandbox actually engages on this host, by a three-leg probe
  ([`boltrig/api/codex_trusted.py:191`](../../../boltrig/api/codex_trusted.py)
  `"_prove_the_host_can_enforce_the_cell_wall(Path(settings.codex_binary), stack_root)"`);
- the cell isolation boundary is in force
  ([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:224`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
  `"assert_cell_isolation_boundary("`).

Both raise rather than warn, "because a wall reported untested reads to every downstream
caller exactly like a wall reported working"
([`boltrig/api/codex_trusted.py:123`](../../../boltrig/api/codex_trusted.py)
`"Raises rather than warns, because a wall reported untested"`).

### 8.2 Gates an operator runs

| target | command | what it proves |
| --- | --- | --- |
| `make codex-pin-health` | `scripts/check_codex_pin_health.py` ([`Makefile:122`](../../../Makefile) `"$(PY) scripts/check_codex_pin_health.py"`) | the pinned binary is PRESENT, digest-matching and not group-writable when `BOLTRIG_CODEX_BINARY` is set; otherwise reports SATISFIABILITY by hashing every candidate under `~/.codex/packages/standalone/releases` |
| `make codex-protocol` | `scripts/check_codex_protocol.py` ([`Makefile:134`](../../../Makefile) `"$(PY) scripts/check_codex_protocol.py"`) | the checked-in manifest and stable-v2 root schema are exact; with `--codex` or `BOLTRIG_CODEX_BINARY` set it also regenerates the 267-file bundle from the real binary and compares canonical digests |
| `make check` | includes both ([`Makefile:223`](../../../Makefile) `"check: invariants lint architecture continuity-projection codex-pin-health structure codex-protocol"`) | fast local subset |
| `make python-quality` | includes `codex-protocol` but **not** `codex-pin-health` ([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure vds-ledgers codex-protocol"`) | the CI-enforced set |

Both scripts are deliberately split between fatal and reported conditions, and both say which
legs actually ran. `check_codex_protocol.py` prints an explicit `NOT VERIFIED` block when the
binary leg was skipped, because the earlier version printed a clean pass while never running
that leg at all ([`scripts/check_codex_protocol.py:369`](../../../scripts/check_codex_protocol.py)
`"the sha256 pin on the actual Codex executable"`).

### 8.3 Diagnosing a degraded turn

The degrade tag is the entry point and it is designed to be actionable. Reading order:

1. `output["_degraded"]["reason"]` on the result, one of:
   `runtime_unavailable`, `no_read_only_phase_scope`, `codex_model_binding_failed:<Class>`,
   `codex_turn_failed:<Class>`, `codex_empty_output`, `codex_empty_output_after_error`,
   `codex_tool_budget_exhausted:<n>`, `permanent_runtime_unavailable:<Class>`,
   `permanent_profile_tenant_mismatch`, `permanent_profile_depth_exceeded`,
   `budget_exceeded`.
2. The application log, which carries the full traceback for a `codex_turn_failed`
   ([`boltrig/fleet/codex_runtime.py:276`](../../../boltrig/fleet/codex_runtime.py)
   `"logger.exception("`) and the full ERROR payload list before an empty turn
   ([`boltrig/fleet/codex_runtime_support.py:25`](../../../boltrig/fleet/codex_runtime_support.py)
   `"logger.warning("`).
3. The cell stderr classification labels on teardown, one of
   `tool-call-unsupported`, `approval-requested`, `tool-execution-started`,
   `tool-call-completed`, `thread-panic`, `panic`
   ([`boltrig/fleet/infrastructure/codex_stdio_transport.py:36`](../../../boltrig/fleet/infrastructure/codex_stdio_transport.py)
   `"_CODEX_STDERR_MARKERS: tuple[tuple[str, str], ...] = ("`).
4. For a tools lane that lost its hands but kept its voice, the log line naming the compiled
   count against the 128 attestation bound
   ([`boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:185`](../../../boltrig/fleet/infrastructure/codex_kernel_tools_phase.py)
   `"compiled %d tools over the"`).

### 8.4 Changing the pin

Decision 0022 is explicit that this is a project, not a chore, and enumerates what a move
requires: a 0.14x standalone release obtained and its digest reviewed, `schemas/codex/<version>/`
regenerated, the collaboration namespace re-verified **against the new binary rather than
assumed**, and the `cliVersion` gate updated in the same change
([`docs/decisions/0022-hold-the-codex-pin-at-0-144-3.md:47`](../../../docs/decisions/0022-hold-the-codex-pin-at-0-144-3.md)
`"When it moves it will need: a 0.14x standalone release obtained"`). The three seams it
names all still exist in the pinned tree and were re-checked here:

- the collaboration namespace `multi_agent_v1`
  ([`boltrig/fleet/infrastructure/codex_native_collaboration_wire.py:12`](../../../boltrig/fleet/infrastructure/codex_native_collaboration_wire.py)
  `"CODEX_NATIVE_COLLAB_NAMESPACE_NAME = \"multi_agent_v1\""`);
- `schemas/codex/` holds 0.144.3 and nothing else (bounded: `ls schemas/codex/`, 2026-08-24);
- the `cliVersion` refusal, now at
  [`boltrig/fleet/infrastructure/codex_runtime_events.py:186`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py)
  `"thread.get(\"cliVersion\") != CODEX_CLI_VERSION"` (decision 0022 cited lines 186-190; the
  check is at 185-191 in this tree, so the record's line reference still lands).

### 8.5 Opening production admission

`docs/CODEX-PRODUCTION-ADMISSION.md` gives an eight-step ordered closure sequence
([`docs/CODEX-PRODUCTION-ADMISSION.md:161`](../../../docs/CODEX-PRODUCTION-ADMISSION.md)
`"Do these in order. Do not flip either production constant early."`). Two of the seven
blockers are declared unreachable with the pinned release: `effective_provider` and
`full_generated_schema_contract`, because 0.144.3 has no pre-thread method that binds either
([`docs/CODEX-PRODUCTION-ADMISSION.md:69`](../../../docs/CODEX-PRODUCTION-ADMISSION.md)
`"0.144.3 has no sufficient pre-thread method"`). The 0.145.0 candidate was screened and
rejected for exactly those two limbs
([`docs/CODEX-PRODUCTION-ADMISSION.md:128`](../../../docs/CODEX-PRODUCTION-ADMISSION.md)
`"do not move the Boltrig pin to 0.145.0"`).

### 8.6 Rolling back

Decision 0012's rollback rule survives as text but has no executable path in this area:
"An in-flight root run never changes engine. Rollback routes new root runs to the previous
release while existing runs finish"
([`docs/decisions/0012-boltrig-codex-opbox-ownership.md:224`](../../../docs/decisions/0012-boltrig-codex-opbox-ownership.md)
`"An in-flight root run never changes engine."`).
The machinery that would implement it, `CodexRolloutPolicy.emergency_rollback` and the
`EngineRoute` enum, exists
([`boltrig/fleet/application/codex_routing.py:117`](../../../boltrig/fleet/application/codex_routing.py)
`"if policy.emergency_rollback:"`) but the only policy ever constructed is
`CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)`
([`boltrig/api/codex_execution.py:57`](../../../boltrig/api/codex_execution.py)
`"_SCAFFOLD_POLICY = CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)"`), so
rollback today is a release operation, not a flag.

## 9. Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| Unknown / retired capability runtime name | **fail-degraded** (not closed, not open): typed `UnavailableRuntime`, nothing executes | [`boltrig/fleet/runtime.py:97`](../../../boltrig/fleet/runtime.py) `"return UnavailableRuntime(requested=kind"` |
| Trusted posture wall | **fail-closed**, raises before any provisioning or bearer mint | [`boltrig/fleet/codex_trusted_wall.py:92`](../../../boltrig/fleet/codex_trusted_wall.py) `"raise CodexTrustedPostureError("` |
| Trusted config factory | **fail-off**: returns `None` and constructs nothing | [`boltrig/api/codex_trusted.py:161`](../../../boltrig/api/codex_trusted.py) `"if not (settings.codex_trusted and settings.codex_binary"` |
| Provider type check | **fail-closed to unavailable** | [`boltrig/fleet/codex_runtime.py:358`](../../../boltrig/fleet/codex_runtime.py) `"if type(provider) is not TrustedProxyCodexPhaseCellProvider:"` |
| Kernel-tools wiring validation | **fail-closed to unavailable**, never a silent downgrade to read-only | [`boltrig/fleet/codex_runtime.py:373`](../../../boltrig/fleet/codex_runtime.py) `"except (TypeError, ValueError):"` |
| Sandbox engagement probe | **fail-closed**, three legs, unproved is refused not skipped | [`boltrig/fleet/infrastructure/codex_sandbox_engagement.py:219`](../../../boltrig/fleet/infrastructure/codex_sandbox_engagement.py) `"There is no third outcome"` |
| Yama ptrace scope | **fail-closed**, unreadable is fatal | [`boltrig/fleet/infrastructure/codex_cell_boundary.py:217`](../../../boltrig/fleet/infrastructure/codex_cell_boundary.py) `"yama ptrace_scope is unreadable, so ptrace is unproved"` |
| Binary digest verification | **fail-closed**, with a TOCTOU re-stat on both sides of the read | [`boltrig/fleet/infrastructure/codex_cell_policy.py:327`](../../../boltrig/fleet/infrastructure/codex_cell_policy.py) `"Codex binary changed while it was being verified"` |
| `cliVersion` mismatch on `thread/started` | **fail-closed**, terminates the phase | [`boltrig/fleet/infrastructure/codex_runtime_events.py:190`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py) `"thread notification policy does not match"` |
| Runtime invalidation notifications (12 methods) | **fail-closed**, terminates the phase | [`boltrig/fleet/infrastructure/codex_runtime_events.py:159`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py) `"Codex pre-thread attestation was invalidated"` |
| The kernel MCP server's own startup update | **exempted**, and only for `status in {starting, ready}` on the exact admitted server name | [`boltrig/fleet/infrastructure/codex_runtime_invalidation.py:54`](../../../boltrig/fleet/infrastructure/codex_runtime_invalidation.py) `"params.get(\"name\") == CODEX_MCP_SERVER_NAME"` |
| Codex server-initiated request, unknown method | **fail-closed** with a typed error; pump survives | [`boltrig/fleet/infrastructure/codex_server_request_handler.py:70`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py) `"unsupported codex server request"` |
| Codex approval prompt, ambiguous label | **fail-closed** with `-32602`; explicitly **not** an auto-deny | [`boltrig/fleet/infrastructure/codex_server_request_handler.py:75`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py) `"we never auto-deny before it either"` |
| Codex approval prompt, resolvable label | **admit** (approve), on the ratio that the kernel is the gate | [`boltrig/fleet/infrastructure/codex_server_request_handler.py:15`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py) `"the faithful, drift-proof answer is to ADMIT every prompted"` |
| Any lifecycle exception in a turn | **fail-degraded**: logged with traceback, tagged, never raised into the caller | [`boltrig/fleet/codex_runtime.py:280`](../../../boltrig/fleet/codex_runtime.py) `"return AgentResult.degrade("` |
| Tool budget exhaustion | **fail-degraded** after interrupting the turn | [`boltrig/fleet/codex_runtime.py:266`](../../../boltrig/fleet/codex_runtime.py) `"with contextlib.suppress(Exception):"` |
| Tool ceiling over the 128 attestation bound | **fail-degraded to voice-without-hands**, logged with both integers, never truncated | [`boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:185`](../../../boltrig/fleet/infrastructure/codex_kernel_tools_phase.py) `"compiled %d tools over the"` |
| Token revocation at run end | **best-effort, suppressed**: a revocation failure never fails the turn | [`boltrig/fleet/codex_runtime.py:235`](../../../boltrig/fleet/codex_runtime.py) `"with contextlib.suppress(Exception):"` |
| Thread cleanup at close | **suppressed inside `run`**, but `close_thread` itself raises if cleanup failed | [`boltrig/fleet/codex_runtime.py:293`](../../../boltrig/fleet/codex_runtime.py) `"await self._lifecycle.close_thread(thread)"` vs [`boltrig/fleet/infrastructure/codex_agent_runtime.py:284`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py) `"raise CodexRuntimeOperationError(\"Codex thread cleanup failed\")"` |
| `shadow_admit` | **FAIL-OPEN by explicit decision**: any failure is logged and swallowed | [`boltrig/api/codex_execution.py:108`](../../../boltrig/api/codex_execution.py) `"except Exception:  # shadow write, fail-open"` |
| `per_cell_uid_mode_available` on an unreadable `/proc` | **fail-closed**: unproven reads as absent | [`boltrig/fleet/infrastructure/cell_privilege.py:268`](../../../boltrig/fleet/infrastructure/cell_privilege.py) `"return False"` |
| Concurrent cells while `config.toml` is unprotected | **fail-closed**: the second acquire is refused outright | [`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:544`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py) `"concurrent Codex cells are refused"` |
| A model-proxy request body that cannot be parsed | **fail-closed**: raises `ToolCeilingViolation`, on the stated ratio that a body we cannot parse is a body whose tool set we cannot verify | [`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py:13`](../../../boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py) `"we cannot parse is a body whose tool set we cannot verify"`, enforced at [`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py:101`](../../../boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py) `"raise ToolCeilingViolation(\"model-call body is not parseable JSON\")"` |
| Production admission | **fail-closed in two independent constants plus a projection that stays red while any blocker remains** | [`boltrig/observability/codex_admission.py:33`](../../../boltrig/observability/codex_admission.py) `"ready = runtime_ready and config_ready and not blockers"` |

**The one deliberate fail-open in this area is `shadow_admit`**, and it is scoped:
it exists only under `BOLTRIG_CODEX_LEDGER`, records an execution-neutral row, and is
declared total ("this method is total: it never raises")
([`boltrig/api/codex_execution.py:94`](../../../boltrig/api/codex_execution.py)
`"This method is total: it never raises."`). Fail-closed
authority is explicitly deferred to the ON-path change.

**The `_probe_for_lane` substitution is worth naming.** When the injected probe is exactly
`QuarantinedCodexPreflightProbe`, the provider wraps it in `BoundCodexSurfacePreflightProbe`
([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:498`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
`"if type(self._probe) is QuarantinedCodexPreflightProbe:"`). The stated reason is that
"test doubles keep the protocol-only seam and cannot accidentally fabricate evidence". The
consequence is that the production composition runs a strictly stronger probe than any test
double can, so a test that injects a fake probe is not exercising the surface-attestation
path at all.

## 10. What is proven

Invariants that bind this subsystem, with their catalogue descriptions and bindings read from
`tests/invariants.yaml`:

| id | what it holds | binding tests |
| --- | --- | --- |
| `FR-RUN-21` | Codex is the only shipped model-backed runtime; script is the only deterministic one; retired names stay inert even with the historical opt-in env var; the module exposes no revival API ([`tests/invariants.yaml:118`](../../../tests/invariants.yaml) `"Codex is the only shipped model-backed agent runtime"`) | `tests/security/test_retired_runtime_gate.py` (3 tests) |
| `FR-RUN-01` | Historical runtimes are retired, not gated; a stale name degrades; doctor reports an enabled retired manifest block ([`tests/invariants.yaml:840`](../../../tests/invariants.yaml) `"Historical third-party agent runtimes are retired, not gated"`) | `test_retired_runtime_gate.py::test_retired_runtime_names_are_inert_even_with_old_opt_in_env`, `tests/unit/test_doctor.py` (2) |
| `FR-RUN-19` | Only the exact reviewed 0.144.3 Linux binary and canonical stable-v2 schema are admitted; experimental APIs disabled; stdio or a private Unix socket only ([`tests/invariants.yaml:107`](../../../tests/invariants.yaml) `"Boltrig admits only the exact reviewed Codex 0.144.3 Linux binary"`) | `tests/unit/test_codex_protocol_pin.py` (2) |
| `SEC-150` | The App Server client admits only the pinned stable omitted-jsonrpc protocol over a bounded local transport, hard-enforces read-only sandbox with local approvals disabled, answers only the one typed server request, refuses every other fail-closed, never exposes peer payloads ([`tests/invariants.yaml:91`](../../../tests/invariants.yaml) `"The first Codex App Server client admits only"`) | `tests/unit/test_codex_app_server.py` (2), `test_codex_server_request_handler.py` (1) |
| `SEC-159` | Config is deterministically composed from a private revalidated snapshot, secretless command auth, read-only sandbox, every reviewed dynamic surface disabled, exact receipt-to-TOML coherence; native subagent admission is exactly zero; production readiness stays false ([`tests/invariants.yaml:154`](../../../tests/invariants.yaml) `"Codex runtime configuration is deterministically composed"`) | `tests/unit/test_codex_runtime_config*.py`, `tests/deploy/test_codex_image_pin_parity.py` |
| `SEC-184` | The kernel-tools lane's one MCP path, run-scoped token in a child env var only, ceiling as exact wire names, proxy offers exactly that set, chokepoint still grant-checks ([`tests/invariants.yaml:309`](../../../tests/invariants.yaml) `"The kernel-tools Codex lane gives a walled cell REAL tool use"`) | 11 tests across `test_codex_kernel_tools_mcp.py`, `test_codex_kernel_tools_lane.py`, `test_codex_runtime_config_mcp.py`, `test_mcp_face.py` |
| `SEC-185` | The wall admits exactly two postures; both refuse production; posture (b) is detected from deployed privilege state ([`tests/invariants.yaml:384`](../../../tests/invariants.yaml) `"The trusted-Codex wall admits exactly two postures"`) | `tests/unit/test_codex_trusted_wall.py` (5), `test_codex_kernel_tools_lane.py` (2), `test_codex_kernel_tools_session_auth.py` (2) |
| `CODEX-COMPOSITION-1` | One trusted provider per serving process, injected into every packaged spawner; the trusted factory is a total no-op when off ([`tests/invariants.yaml:25`](../../../tests/invariants.yaml) `"Each serving process constructs at most one trusted Codex provider"`) | `tests/unit/test_codex_trusted_composition.py` (9) plus 2 more |
| `CODEX-APPROVAL-1..4` | The approval answer is explicit, prompt, label-derived, gating-free, and never crashes the pump ([`tests/invariants.yaml:39`](../../../tests/invariants.yaml) `"NEVER terminates the single-reader notification pump"`; the other three ids sit at lines 44, 48 and 52 of the same file) | `test_codex_app_server.py`, `test_codex_server_request_handler.py` |
| `SEC-170` / `SEC-172` / `SEC-173` | The ledger scaffold is a total no-op behind its flag; the shadow write is execution-neutral and fail-open ([`tests/invariants.yaml:202`](../../../tests/invariants.yaml) `"The Codex read-only ledger scaffold is a total no-op behind BOLTRIG_CODEX_LEDGER"`; SEC-172 at line 216, SEC-173 at line 222) | `test_codex_execution.py`, `test_codex_shadow_root_admission.py`, `test_codex_pump_root_admission.py` |
| `SEC-155` / `SEC-156` | Bounded deterministic read-only workspace snapshot; only digest-pinned selected skills materialize ([`tests/invariants.yaml:141`](../../../tests/invariants.yaml) `"bounded deterministic read-only workspace snapshot"`; SEC-156 at line 146) | `test_skill_artifacts.py`, `test_skill_attestation.py`, `test_skill_discovery.py` |
| `US-FLT-07` | Degraded results are marked degraded end to end and never presented as ordinary success ([`tests/invariants.yaml:465`](../../../tests/invariants.yaml) `"Degraded results are first-class"`) | `tests/integration/test_degraded_honesty.py` (3), `test_durable_delegation.py` |
| `P9` | Backend unavailability degrades gracefully, never crashes ([`tests/invariants.yaml:419`](../../../tests/invariants.yaml) `"Backend unavailability degrades gracefully, never crashes"`) | bound to two tests in the ratelimit and emotion areas, **not** to any Codex test |

**Tests that exist but bind no invariant.** The Codex degrade contract, the tool-step cap and
the token-usage accounting are covered by 9, 5 and 11 tests respectively
(`tests/unit/test_codex_runtime.py`, `test_codex_tool_step_cap.py`, `test_codex_token_usage.py`),
and only one of those files carries an `@pytest.mark.invariant` marker at all
(bounded: `rg -n "pytest.mark.invariant"` over all three files, 2026-08-24, pinned tree; the
single hit is [`tests/unit/test_codex_runtime.py:174`](../../../tests/unit/test_codex_runtime.py)
`"@pytest.mark.invariant(\"SEC-WRK-02\")"`, which binds `SEC-WRK-02`). See RISKS.

## 11. RISKS

RISK: **Decision 0020's condition L3 is no longer satisfied by the pinned tree.** L3 requires
the manifest's multi-runtime ROUTING MECHANISM to stay live and "at least one non-Codex
governed leaf buildable and re-wirable by configuration alone, without a fresh order, as a
quarantine fallback, until `production_ready` is unblocked"
([`docs/decisions/0020-retire-the-pi-lane.md:12`](../../../docs/decisions/0020-retire-the-pi-lane.md)).
`build_runtime` has no roster, no `_LEGACY_RUNTIME_KINDS`, and no env gate: the four lanes the
addendum names (`openai`, `claude-api`, `opencode`, `rivet`) all reach the unknown-kind
fallback ([`boltrig/fleet/runtime.py:97`](../../../boltrig/fleet/runtime.py)
`"return UnavailableRuntime(requested=kind"`). `FR-RUN-21`, the instrument L3 named as its
proof, has been **re-described to assert the opposite property**: its current text is "retired
provider-native, OpenCode, Rivet, Pi and Hermes names remain inert"
([`tests/invariants.yaml:118`](../../../tests/invariants.yaml)
`"Rivet, Pi and Hermes names remain inert"`), and its binding test file is
`tests/security/test_retired_runtime_gate.py`, not the
`tests/security/test_legacy_runtime_gate.py` that 0020 cites (bounded:
`ls tests/security/ | rg "legacy|retired"`, 2026-08-24, pinned tree, one file, the retired one).
`production_ready` is still False
([`boltrig/fleet/infrastructure/codex_agent_runtime.py:61`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
`"production_ready = False"`),
so the condition's trigger has not been discharged either. Nothing in this tree records the
authority under which the seam was removed.

RISK: **The 0.144.3 literal is written in at least six places and only two are mechanically
bound to the pin authority.** Bound: `codex_binary_pin.CODEX_CLI_VERSION` to
`check_codex_protocol.PIN_VERSION` ([`tests/unit/test_codex_cell_policy.py:25`](../../../tests/unit/test_codex_cell_policy.py)
`"policy.CODEX_CLI_VERSION == check_codex_protocol.PIN_VERSION"`) and to both Dockerfiles
([`tests/deploy/test_codex_image_pin_parity.py:18`](../../../tests/deploy/test_codex_image_pin_parity.py)
`"f\"ARG CODEX_VERSION={codex_binary_pin.CODEX_CLI_VERSION}\""`). Unbound copies:
`CODEX_RUNTIME_CLI_VERSION` ([`boltrig/fleet/infrastructure/codex_runtime_config.py:41`](../../../boltrig/fleet/infrastructure/codex_runtime_config.py)
`"CODEX_RUNTIME_CLI_VERSION = \"0.144.3\""`),
`CODEX_SKILL_POLICY_VERSION` ([`boltrig/fleet/infrastructure/skill_config.py:22`](../../../boltrig/fleet/infrastructure/skill_config.py)
`"CODEX_SKILL_POLICY_VERSION = \"0.144.3\""`),
`stage_desktop_codex.VERSION` ([`scripts/stage_desktop_codex.py:20`](../../../scripts/stage_desktop_codex.py)
`"VERSION = \"0.144.3\""`),
and `REQUIRED_RELEASE_CODEX_VERSION`
([`apps/worker/src-tauri/src/local_agent.rs:31`](../../../apps/worker/src-tauri/src/local_agent.rs)
`"const REQUIRED_RELEASE_CODEX_VERSION: &str = \"0.144.3\";"`);
the last three are asserted only against their own literal string
([`tests/unit/test_skill_config.py:96`](../../../tests/unit/test_skill_config.py)
`"CODEX_SKILL_POLICY_VERSION == \"0.144.3\""`).

RISK: **`AgentResult.degrade` returns `ok=True`, so a caller that checks only `ok` treats a
degrade as a success.** The marker is `degraded` and the reason is nested under
`output["_degraded"]` ([`boltrig/fleet/result.py:132`](../../../boltrig/fleet/result.py)
`"ok=True,"`). The `_project_agent_result` path in `spawn_entrypoints` re-adds a default
`_degraded` marker when one is missing
([`boltrig/fleet/spawn_entrypoints.py:146`](../../../boltrig/fleet/spawn_entrypoints.py)
`"output.setdefault(\"_degraded\", {\"reason\": \"degraded\"})"`), which is a symptom of the
same shape.

RISK: **`UnavailableRuntime` inherits `runtime = "python-script"` from `ScriptRuntime` rather
than reporting the requested name.** Any consumer reading `runtime.runtime` (as
`PermanentAgentRuntime.__init__` does for the capability, and as any future observability code
might) sees a script runtime where a Codex lane was requested; the requested name survives only
inside `output["_degraded"]["runtime"]`
([`boltrig/fleet/runtime.py:61`](../../../boltrig/fleet/runtime.py)
`"class UnavailableRuntime(ScriptRuntime):"`).

RISK: **The Codex degrade contract, the tool-step cap and the token-usage accounting bind no
invariant.** 25 tests across three files, one invariant marker between them (bounded:
`rg -n "pytest.mark.invariant" tests/unit/test_codex_runtime.py tests/unit/test_codex_tool_step_cap.py
tests/unit/test_codex_token_usage.py`, 2026-08-24, pinned tree). `P9`, the doctrine these tests
enforce, is bound to two tests in unrelated areas
([`tests/invariants.yaml:421`](../../../tests/invariants.yaml)
`"tests/kernel/test_ratelimit_degraded.py::test_degraded_mode_when_backend_down"`), so deleting
the Codex degrade tests would not move any catalogue number.

RISK: **`BOLTRIG_CODEX_MAX_TOOL_STEPS=0` silently uncaps a runaway tool loop.** The code calls
this "the operator's call, never a fallback"
([`boltrig/fleet/codex_runtime_support.py:58`](../../../boltrig/fleet/codex_runtime_support.py)
`"disables the cap"`), and it is read from the ambient process environment at
`CodexRuntime` construction rather than from validated settings
([`boltrig/fleet/codex_runtime_support.py:66`](../../../boltrig/fleet/codex_runtime_support.py)
`"raw = os.environ.get(_MAX_TOOL_STEPS_ENV, \"\").strip()"`). No doctor or readiness check
reports that the cap is off (bounded: `rg -n "BOLTRIG_CODEX_MAX_TOOL_STEPS" boltrig/ scripts/`,
2026-08-24, two hits, both in that module).

RISK: **The approval handler admits every prompted Codex tool call, including calls to Codex's
own built-in tools if any were ever offered.** The refusal of those built-ins lives entirely in
the per-cell model proxy's request rewriting, not in the approval answer
([`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py:6`](../../../boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py)
`"cannot suppress them"`). The handler's own docstring is explicit that a human veto
for the LOW class is "deliberately omitted"
([`boltrig/fleet/infrastructure/codex_server_request_handler.py:20`](../../../boltrig/fleet/infrastructure/codex_server_request_handler.py)
`"veto for the LOW class is deliberately omitted"`).
This is consistent with decision 0023 (no model judges an approval) but it means the Codex-side
prompt is not a second gate, and a regression in the proxy ceiling would have no approval-side
backstop.

RISK: **`SupervisedCodexPhaseCellProvider` is dead in the production composition.** It is
constructed only in tests (bounded: `rg -n "SupervisedCodexPhaseCellProvider" .`, 2026-08-24,
pinned tree: 8 hits in two test files, one class definition, one `__all__` entry). It runs a
weaker path than the live provider: no posture wall, no boundary proof, no ingress, no model
proxy, and `CODEX_APP_SERVER_BASE_ARGUMENTS` with no per-cell pins
([`boltrig/fleet/infrastructure/codex_runtime_admission.py:250`](../../../boltrig/fleet/infrastructure/codex_runtime_admission.py)
`"arguments=CODEX_APP_SERVER_BASE_ARGUMENTS"`). A future caller reaching for it would get a cell
with none of the guarantees this spec describes.

RISK: **`_prove_the_host_can_enforce_the_cell_wall` shells out to the pinned Codex binary at
process composition time**, with a default 60-second timeout and a maximum of 300
([`boltrig/fleet/infrastructure/codex_sandbox_engagement.py:50`](../../../boltrig/fleet/infrastructure/codex_sandbox_engagement.py)
`"DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0"`). Three subprocess runs of a real Codex binary sit on the
API's startup path whenever `BOLTRIG_CODEX_TRUSTED` is set.

RISK: **The trusted composition's model-proxy grant store is in-memory**, so grants do not
survive a process restart and are not visible to a sibling replica
([`boltrig/api/codex_trusted.py:199`](../../../boltrig/api/codex_trusted.py)
`"grant_store = MemoryModelProxyGrantStore()"`). A Postgres adapter exists
(`postgres_model_proxy_grants.py`) and is not wired here.

RISK: **`api/codex_execution.py` reads `store._pool`, a private attribute**, and says so
([`boltrig/api/codex_execution.py:153`](../../../boltrig/api/codex_execution.py)
`"pool = store._pool"`). It is guarded only by the flag being off by default.

RISK: **G3 is open and recorded as open**: the cell's `config.toml` carries `auth.command` and
lives in a `CODEX_HOME` the cell uid owns, so under the shared-uid posture a sibling can rewrite
it; the mitigation is a refusal to run two cells at once, not isolation
([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:40`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
`"so G3 is OPEN"`). The managed config defends named leaves but not the tables they sit in:
"an attacker-supplied `[mcp_servers.attacker]` with its own `command` survives"
([`deploy/codex/managed_config.toml:19`](../../../deploy/codex/managed_config.toml)
`"[mcp_servers.attacker] with its own \"command\" survives"`).

RISK: **Native-subagent limits are detection tripwires, not admission control, and the code says
so.** A notification arrives after the App Server has begun the action, so exceeding a limit
terminates the phase but cannot prove the action was prevented
([`boltrig/fleet/infrastructure/codex_runtime_events.py:72`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py)
`"a notification arrives after App Server has begun the action"`). The compensating control is
that both shipped lanes set the ceiling to zero.

RISK: **`make python-quality`, the CI-enforced set, does not include `codex-pin-health`**
([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure
vds-ledgers codex-protocol"`). The binary-presence check runs only in `make check`, which the
Makefile itself describes as "NOT what CI enforces"
([`Makefile:223`](../../../Makefile)).

RISK: **`README.md` and `docs/architecture/engine-components.md` both claim retired runtimes were
removed including "binaries"**
([`docs/architecture/engine-components.md:314`](../../../docs/architecture/engine-components.md)
`"There is no feature flag, provider client, subprocess wrapper, binary, or plugin that can
revive a retired lane."`). That claim holds for the pinned tree, but the same tree does ship a
mechanism that downloads and stages Codex binaries at release time for three platforms
([`scripts/stage_desktop_codex.py:24`](../../../scripts/stage_desktop_codex.py) `"PLATFORMS = {"`),
so a reader should not generalise the sentence to "this repository contains no agent binaries".

## 12. OPEN QUESTIONS

1. **Under what authority was the multi-runtime routing seam removed?** Decision 0020's L3
   forbids emptying the roster while `production_ready` is False, and `production_ready` is
   still False. Nothing in `docs/decisions/` records a superseding order (bounded:
   `rg -ni "_LEGACY_RUNTIME_KINDS|ENABLE_LEGACY_RUNTIMES" docs/`, 2026-08-24, pinned tree: hits
   only in 0020 itself, `docs/HANDOVER-2026-07-23.md` and `docs/findings/2026-07-27-*`).
   `docs/HANDOVER-2026-07-23.md:111` says "`BOLTRIG_ENABLE_LEGACY_RUNTIMES` removed", which is a
   note, not an authority. **Settled by**: producing the ruling or decision record that
   discharged L3, or by re-instating the seam.
2. **Is `EngineRoute.CODEX_APP_SERVER` reachable at all today?** The router can return it, but
   the only policy constructed anywhere in `boltrig/` is `mode=OFF`
   ([`boltrig/api/codex_execution.py:57`](../../../boltrig/api/codex_execution.py)
   `"_SCAFFOLD_POLICY = CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)"`), and the
   shadow caller hard-codes `CodexCompatibility.INELIGIBLE`
   ([`boltrig/api/codex_execution.py:105`](../../../boltrig/api/codex_execution.py)
   `"compatibility=CodexCompatibility.INELIGIBLE,"`). I could not find
   any code path that would ever construct a non-OFF policy (bounded:
   `rg -n "CodexRolloutPolicy\(" boltrig/`, 2026-08-24, pinned tree, one hit, at line 57).
   **Settled by**: identifying the intended
   generation source, which the module itself defers ("the real generation-source question ... is
   deferred to the later PR that turns the policy ON").
3. **Does `CodexRuntime` ever run under posture (b) in a real deployment?** The wall admits it and
   `test_codex_kernel_tools_session_auth.py` exercises it, but I did not read `cell_spawner.py`
   or `cell_slots.py`, so I cannot state from the code I opened whether the privileged entrypoint
   in `scripts/kernel-entrypoint.py` actually hands the dropped API a spawner socket in the
   shipped compose. **Settled by**: reading `scripts/kernel-entrypoint.py` against
   `docker-compose.yml`'s kernel service, which is the deployment area's scope.
4. **What is the intended relationship between `CODEX_SKILL_POLICY_VERSION` and the binary pin?**
   Both are `"0.144.3"` and both are checked against their own literal. If they are meant to be
   the same fact they should share one authority. **Settled by**: an author statement, or a gate
   that compares them.
5. **Is the `output_schema` path on `turn/start` used anywhere on the live path?** The protocol
   supports it and `codex_phase_result_schema.py` builds a strict phase-result schema, but
   `CodexRuntime._run_phase` constructs `RuntimeTurnSpec` without one
   ([`boltrig/fleet/codex_runtime.py:256`](../../../boltrig/fleet/codex_runtime.py)
   `"RuntimeTurnSpec(thread=thread, prompt=prompt, client_message_id=uuid.uuid4().hex)"`).
   I did not read `codex_phase_result_parser.py` or its callers. **Settled by**: enumerating
   callers of `phase_result_output_schema`.
6. **Does anything consume `AgentResult.new_work_items` from the Codex lane?** The field exists
   and the docstring cites `US-EXE-04` caps, but `CodexRuntime` never populates it. **Settled by**:
   a search over the department-head and pump areas, which own that field.
7. **Is the per-cell model-proxy `stream_idle_timeout_ms = 300000` reconciled with the
   `_upstream_client` read timeout of 300s?** Both are 300 seconds
   ([`boltrig/fleet/infrastructure/codex_runtime_config_toml.py:212`](../../../boltrig/fleet/infrastructure/codex_runtime_config_toml.py)
   `"stream_idle_timeout_ms = 300000"`,
   [`boltrig/api/codex_trusted.py:146`](../../../boltrig/api/codex_trusted.py) `"read=300.0"`), which
   means the two can expire together. Whether that is intended or a coincidence is not stated.
   **Settled by**: an author statement.
8. **What happens to an in-flight cell when `close_thread` reports `cleanup_failed`?**
   `CodexRuntime._run_phase` suppresses the exception, so the caller sees a normal result while
   `CodexAgentRuntime.close_thread` considered the cleanup failed
   ([`boltrig/fleet/codex_runtime.py:293`](../../../boltrig/fleet/codex_runtime.py)
   `"await self._lifecycle.close_thread(thread)"` versus
   [`boltrig/fleet/infrastructure/codex_agent_runtime.py:284`](../../../boltrig/fleet/infrastructure/codex_agent_runtime.py)
   `"raise CodexRuntimeOperationError(\"Codex thread cleanup failed\")"`).
   Whether a leaked cell is then reaped depends on the provider's reaper, which awaits
   `cell.wait_closed()` before tearing the proxy, scope and ingress down
   ([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:637`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
   `"await cell.wait_closed()"`). **Settled by**: reading `InitializedCodexCell.aclose` and its
   monitor, which I enumerated but did not read line by line.

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-0400 | The `Runtime` protocol declares `runtime`, `cost_tier` and `async run(prompt, context, *, tools) -> AgentResult`, and implementations are stateless per call. | IMPLEMENTED | `boltrig/fleet/runtime.py:23` `"class Runtime(Protocol):"` | FR-RUN-21 |
| BT-REQ-0401 | `build_runtime` maps `codex` to the trusted Codex constructor, `script`/`python-script`/`go-binary` to `ScriptRuntime`, and every other name to `UnavailableRuntime`. | IMPLEMENTED | `tests/security/test_retired_runtime_gate.py::test_script_remains_the_only_non_codex_runtime` | FR-RUN-21 |
| BT-REQ-0402 | `build_runtime` accepts an `endpoint_lookup` argument for call-shape compatibility and discards it unread. | IMPLEMENTED-UNTESTED | `boltrig/fleet/runtime.py:89` `"del endpoint_lookup"`; no test asserts the discard (bounded: `rg -n "endpoint_lookup" tests/`) | - |
| BT-REQ-0403 | `UnavailableRuntime` executes nothing and returns a degraded result naming the requested runtime and reason `runtime_unavailable`. | IMPLEMENTED | `tests/security/test_retired_runtime_gate.py::test_retired_runtime_names_are_inert_even_with_old_opt_in_env` | FR-RUN-01 |
| BT-REQ-0404 | `AgentResult.degrade` returns `ok=True` with `degraded=True` and never embeds the prompt, carrying only its sha256 and byte length. | IMPLEMENTED | `boltrig/fleet/result.py:135` `"\"prompt_sha256\": hashlib.sha256(prompt_bytes).hexdigest()"` | US-FLT-07 |
| BT-REQ-0405 | `degrade_reason` is bounded to 200 characters and carries a runtime tag plus an exception class name, never prompt, output or exception args. | IMPLEMENTED-UNTESTED | `boltrig/fleet/result.py:96` `"return str(reason)[:200] if reason else None"` | - |
| BT-REQ-0406 | The user-facing reply is `output["text"]`; `summary` is the audit line and only the fallback. | IMPLEMENTED | `boltrig/fleet/result.py:167` `"return text or result.get(\"summary\")"` | - |
| BT-REQ-0407 | `ScriptRuntime` is deterministic, offline and non-model, reporting zero tokens and zero cost. | IMPLEMENTED | `boltrig/fleet/runtime.py:56` `"tokens_used=0,"` | FR-RUN-21 |
| BT-REQ-0408 | No module under `boltrig/` defines or exports a provider-native, OpenCode, Rivet, Pi or Hermes runtime class. | IMPLEMENTED | `tests/security/test_retired_runtime_gate.py::test_runtime_module_exposes_no_legacy_revival_api`; bounded: `rg -ni "opencode\|rivet\|pi_sidecar\|PiRuntime" boltrig/ scripts/ services/ deploy/`, 2026-08-24 | FR-RUN-21 |
| BT-REQ-0409 | `BOLTRIG_ENABLE_LEGACY_RUNTIMES` is read by no code in `boltrig/`; setting it changes nothing. | IMPLEMENTED | `tests/security/test_retired_runtime_gate.py:34` `"monkeypatch.setenv(\"BOLTRIG_ENABLE_LEGACY_RUNTIMES\", \"1\")"` | FR-RUN-21 |
| BT-REQ-0410 | `boltrig doctor` reports a `warn` (never a deploy block) for a manifest that enables any of the eight retired runtime names. | IMPLEMENTED | `boltrig/api/doctor.py:352` `"for kind in _RETIRED_RUNTIMES:"` | FR-RUN-01 |
| BT-REQ-0411 | The retired-name set is exactly `pi hermes openai claude-api opencode rivet rivet_agentos rivet-agentos`. | IMPLEMENTED | `boltrig/api/doctor.py:329` `"\"pi hermes openai claude-api opencode rivet rivet_agentos rivet-agentos\".split()"` | FR-RUN-01 |
| BT-REQ-0412 | No retired-runtime binary, plugin or vendored client is present in the tree. | IMPLEMENTED | bounded: `find . -path ./.git -prune -o -type f -size +2M -print`, 2026-08-24, six media assets only; `rg -ni "opencode\|rivet\|pi_sidecar" apps/ familiar/ ios/ sdks/ libraries/ tools/ site/ --glob '!*.json'` returns nothing | FR-RUN-21 |
| BT-REQ-0413 | No configuration-only path can construct a governed non-Codex, non-script agent lane. | IMPLEMENTED | `boltrig/fleet/runtime.py:95` `"if kind in {\"script\", \"python-script\", \"go-binary\"}:"` | FR-RUN-21 |
| BT-REQ-0414 | The `AgentRuntime` port declares exactly seven members: `start_thread`, `resume_thread`, `start_turn`, `steer_turn`, `interrupt_turn`, `events`, `close_thread`. | IMPLEMENTED-UNTESTED | `boltrig/fleet/ports/runtime.py:59` `"async def start_thread(self, spec: RuntimeThreadSpec)"` | - |
| BT-REQ-0415 | `RuntimeThreadSpec` defaults to `PhaseMode.READ_ONLY` and `SandboxPolicy.READ_ONLY`. | IMPLEMENTED-UNTESTED | `boltrig/fleet/ports/runtime.py:30` `"mode: PhaseMode = PhaseMode.READ_ONLY"` | - |
| BT-REQ-0416 | A turn spec carries only user input; policy is never expressed through the prompt. | IMPLEMENTED-UNTESTED | `boltrig/fleet/ports/runtime.py:37` `"policy remains outside the prompt"` | - |
| BT-REQ-0417 | `CodexAgentRuntime.name` is `codex_app_server` and `production_ready` is the constant `False`. | IMPLEMENTED | `tests/security/test_codex_admission_projection.py` via `codex_release_posture`; `boltrig/fleet/infrastructure/codex_agent_runtime.py:61` `"production_ready = False"` | SEC-159 |
| BT-REQ-0418 | `CodexAgentRuntime` refuses construction unless `allow_test_only_runtime=True`. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_agent_runtime.py:75` `"Codex runtime requires unresolved production isolation controls"` | SEC-159 |
| BT-REQ-0419 | At most 64 Codex phases are active per runtime instance, and one phase never has two owners. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_agent_runtime.py:337` `"phase already has a Codex owner"` | - |
| BT-REQ-0420 | `events()` never carries model output; the turn's text is read back through `read_turn_output`. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_agent_runtime.py:289` `"is a deliberately content-free lifecycle ledger"` | SEC-150 |
| BT-REQ-0421 | Every `thread/start` and `thread/resume` sends `approvalPolicy: never`, `sandbox: read-only`, and `thread/start` additionally sends `ephemeral: true`. | IMPLEMENTED | `tests/unit/test_codex_app_server.py::test_read_only_lifecycle_uses_exact_monotonic_stable_shapes` | SEC-150 |
| BT-REQ-0422 | Resume, steer and interrupt bind to the exact requested thread and turn identifiers; a mismatch is a binding terminal. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_agent_runtime.py:244` `"Codex steered another turn"` | - |
| BT-REQ-0423 | `close_thread` raises `CodexRuntimeOperationError` when cell cleanup failed. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_agent_runtime.py:284` `"Codex thread cleanup failed"` | - |
| BT-REQ-0424 | The event stream admits exactly one consumer at a time. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_runtime_actor.py:184` `"Codex event stream already has a consumer"` | - |
| BT-REQ-0425 | Wire frames omit the `jsonrpc` header, use exact key sets, reject duplicate JSON keys and non-finite numbers, and are capped at 1 MiB per line. | IMPLEMENTED | `tests/unit/test_codex_app_server_adversarial.py`; `boltrig/fleet/infrastructure/codex_protocol.py:241` `"jsonrpc header must be omitted"` | SEC-150 |
| BT-REQ-0426 | No protocol error message includes a request or response payload. | IMPLEMENTED | `tests/unit/test_codex_server_request_handler.py::test_the_error_arm_carries_no_request_params` | SEC-150 |
| BT-REQ-0427 | `initialize` declares `capabilities.experimentalApi = false`. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_app_server.py:100` `"\"capabilities\": {\"experimentalApi\": False},"` | FR-RUN-19 |
| BT-REQ-0428 | The only server-initiated request the client answers is `item/tool/requestUserInput`; every other method is refused with `-32601` without crashing the pump. | IMPLEMENTED | `tests/unit/test_codex_app_server.py::test_an_unhandled_server_request_is_refused_typed_and_never_crashes_the_pump` | CODEX-APPROVAL-1 |
| BT-REQ-0429 | The approve label is read from Codex's own offered options; zero or multiple candidates is refused with `-32602` and never an auto-deny. | IMPLEMENTED | `tests/unit/test_codex_server_request_handler.py::test_an_ambiguous_approve_option_fails_closed` | CODEX-APPROVAL-4 |
| BT-REQ-0430 | The approval handler inspects no verb consequence and duplicates no kernel predicate, so it cannot drift from the kernel gate. | IMPLEMENTED | `tests/unit/test_codex_server_request_handler.py::test_the_handler_makes_no_gating_decision_so_it_cannot_drift` | CODEX-APPROVAL-2 |
| BT-REQ-0431 | A server request is answered on a side task and its failure never terminates the single-reader notification pump. | IMPLEMENTED | `tests/unit/test_codex_app_server.py::test_a_tool_approval_is_answered_explicitly_and_the_pump_survives` | CODEX-APPROVAL-1 |
| BT-REQ-0432 | A `thread/started` notification whose `cliVersion` is not the pinned version terminates the phase. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_runtime_events.py:186` `"thread.get(\"cliVersion\") != CODEX_CLI_VERSION"`; the notification tests exist but no marker binds this branch | - |
| BT-REQ-0433 | Twelve named notification methods invalidate quarantined evidence and terminate the phase; the sole exemption is the admitted kernel MCP server's `starting`/`ready` startup update. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_runtime_invalidation.py:54` `"params.get(\"name\") == CODEX_MCP_SERVER_NAME"` | SEC-184 |
| BT-REQ-0434 | A token-usage report from a foreign thread is recorded as an observation and never billed to this run. | IMPLEMENTED | `tests/unit/test_codex_token_usage.py::test_events_after_completion_are_not_billed`; `boltrig/fleet/infrastructure/codex_runtime_events.py:243` `"\"observation\": \"native_token_usage\""` | - |
| BT-REQ-0435 | An unrecognised notification method produces an UNKNOWN event carrying only a digest of the method name. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_runtime_events.py:165` `"payload={\"method_digest\": _method_digest(notification.method)},"` | - |
| BT-REQ-0436 | The pinned Codex CLI version is `0.144.3` and exactly two reviewed Linux artifact digests are admitted, one x86_64-musl and one aarch64-musl. | IMPLEMENTED | `tests/unit/test_codex_cell_policy.py:25` `"policy.CODEX_CLI_VERSION == check_codex_protocol.PIN_VERSION == \"0.144.3\""` | FR-RUN-19 |
| BT-REQ-0437 | Binary verification requires a regular non-symlink executable that is not group- or world-writable, opens it `O_NOFOLLOW`, re-stats before and after hashing, and admits only a digest in the reviewed set. | IMPLEMENTED | `tests/unit/test_codex_cell_supervisor_hardening.py`; `boltrig/fleet/infrastructure/codex_cell_policy.py:327` `"Codex binary changed while it was being verified"` | SEC-159 |
| BT-REQ-0438 | `check_codex_protocol.py` always verifies the checked-in manifest and root schema, verifies the installed binary and its regenerated 267-file bundle only when a binary path is supplied, and states which legs ran. | IMPLEMENTED | `tests/unit/test_codex_protocol_pin.py::test_checked_in_codex_protocol_pin_is_exact` | FR-RUN-19 |
| BT-REQ-0439 | `check_codex_pin_health.py` is fatal only when `BOLTRIG_CODEX_BINARY` is set, reports satisfiability otherwise, and is never fatal on version drift. | IMPLEMENTED-UNTESTED | `scripts/check_codex_pin_health.py:140` `"BOLTRIG_CODEX_BINARY is unset: this box is not configured to spawn cells."`; bounded: `rg -n "check_codex_pin_health" tests/` returns nothing | - |
| BT-REQ-0440 | Both release Dockerfiles declare the same version, both digests and both target triples as the runtime pin module. | IMPLEMENTED | `tests/deploy/test_codex_image_pin_parity.py::test_release_images_install_every_runtime_reviewed_codex_artifact` | SEC-159 |
| BT-REQ-0441 | The version literal `0.144.3` also appears in `codex_runtime_config`, `skill_config`, `stage_desktop_codex` and the Tauri local agent without a mechanical binding to the pin authority. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/skill_config.py:22` `"CODEX_SKILL_POLICY_VERSION = \"0.144.3\""` | - |
| BT-REQ-0442 | The protocol manifest permits only `stdio` and `private-unix-socket` transports and records `remoteWebSocketAllowed: false`. | IMPLEMENTED | `scripts/check_codex_protocol.py:120` `"_exact(transport[\"remoteWebSocketAllowed\"], False, \"remote WebSocket policy\")"` | FR-RUN-19 |
| BT-REQ-0443 | The trusted wall requires `BOLTRIG_CODEX_TRUSTED` under both postures. | IMPLEMENTED | `tests/unit/test_codex_trusted_wall.py::test_per_cell_posture_still_requires_the_trusted_flag` | SEC-185 |
| BT-REQ-0444 | The trusted wall refuses any production or staging signal under both postures. | IMPLEMENTED | `tests/unit/test_codex_trusted_wall.py::test_per_cell_posture_still_refuses_a_production_signal` | SEC-185 |
| BT-REQ-0445 | Posture (a) is `BOLTRIG_DEV_AUTH=1` with no OIDC, Cloudflare Access or session-login ingress configured. | IMPLEMENTED | `boltrig/fleet/codex_trusted_wall.py:79` `"if s.dev_auth and not real_ingress:"` | SEC-185 |
| BT-REQ-0446 | Posture (b) is detected from the deployed privilege state (a live inherited spawner socket or uid-0-with-capability), never asserted by an operator flag. | IMPLEMENTED | `tests/unit/test_codex_trusted_wall.py::test_per_cell_posture_admits_session_auth_without_dev_auth` | SEC-185 |
| BT-REQ-0447 | A real ingress posture without per-cell uids is refused before any admission or bearer mint. | IMPLEMENTED | `tests/unit/test_codex_trusted_wall.py::test_session_auth_without_per_cell_uids_is_refused` | SEC-185 |
| BT-REQ-0448 | The wall is asserted at three seams: the composition factory's flag check, `build_trusted_codex_runtime`, and `provider.acquire`. | IMPLEMENTED | `tests/unit/test_codex_kernel_tools_lane.py::test_acquire_refuses_session_auth_without_per_cell_uids`; `boltrig/fleet/codex_runtime.py:357` `"require_codex_trusted_posture()"` | SEC-185 |
| BT-REQ-0449 | `build_trusted_codex_config` returns `None` unless the trusted flag, the binary path and the stack root are all present, constructing nothing. | IMPLEMENTED | `tests/unit/test_codex_trusted_composition.py::test_returns_none_when_codex_trusted_off` | CODEX-COMPOSITION-1 |
| BT-REQ-0450 | `build_trusted_codex_runtime` accepts only an exact `TrustedProxyCodexPhaseCellProvider`; any other object yields a typed unavailable runtime. | IMPLEMENTED-UNTESTED | `boltrig/fleet/codex_runtime.py:358` `"if type(provider) is not TrustedProxyCodexPhaseCellProvider:"` | - |
| BT-REQ-0451 | The trusted provider refuses construction unless its supervisor was built with `auth=None`, so the cell environment can never carry the upstream key. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:194` `"trusted Codex supervisor must be constructed with auth=None (D2)"` | SEC-159 |
| BT-REQ-0452 | Composition proves the read-only sandbox actually engages on the host with three legs (unsandboxed write succeeds, sandboxed write leaves no artefact, sandboxed read succeeds) and refuses to build a provider otherwise. | IMPLEMENTED | `tests/unit/test_codex_sandbox_engagement.py`; `boltrig/fleet/infrastructure/codex_sandbox_engagement.py:219` `"There is no third outcome"` | - |
| BT-REQ-0453 | Composition proves the shared auth helper is a non-symlink regular file, foreign-owned, unwritable by this account, outside the mutable stack root, with an unwritable directory chain, and that Yama `ptrace_scope >= 1`. | IMPLEMENTED | `tests/unit/test_codex_cell_boundary.py`; `boltrig/fleet/infrastructure/codex_cell_boundary.py:256` `"shared auth helper must lie outside the mutable stack root"` | - |
| BT-REQ-0454 | While `config.toml` is not protected by per-cell uids, a second concurrent cell is refused outright. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:544` `"concurrent Codex cells are refused"` | SEC-159 |
| BT-REQ-0455 | Each cell's bearer ingress binds a fresh random abstract socket name, never a filesystem path derived from the cell id. | IMPLEMENTED | `tests/unit/test_codex_trusted_proxy_ingress.py`; `boltrig/fleet/infrastructure/codex_trusted_proxy_ingress.py:213` `"return f\"@boltrig-mp-{secrets.token_hex(_SOCKET_TOKEN_BYTES)}\""` | - |
| BT-REQ-0456 | A bearer is minted per attested peer connection at a strictly higher generation, and per-cell uids are re-confirmed against the kernel at the instant of issuance. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_trusted_proxy_ingress.py:274` `"assert_cell_process_unprivileged(attested.pid, expected_uid=expected_cell_uid)"` | SEC-185 |
| BT-REQ-0457 | A cell identity is registered from the slot the cell was ALLOCATED, never from the observed process credentials, and root is never a lawful cell identity. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_trusted_proxy_ingress.py:150` `"a cell identity may never be registered as root"` | - |
| BT-REQ-0458 | Production admission is closed by two independent constants and the shared projection reports `ready` only when both are true and no quarantined blocker remains. | IMPLEMENTED | `tests/security/test_codex_admission_projection.py`; `boltrig/observability/codex_admission.py:33` `"ready = runtime_ready and config_ready and not blockers"` | SEC-159 |
| BT-REQ-0459 | `QuarantinedCodexPreflightReceipt.production_complete` is always `False` and the receipt must carry the complete seven-blocker tuple. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_preflight_receipt.py:71` `"quarantined receipt omitted a production blocker"` | SEC-159 |
| BT-REQ-0460 | A quarantined receipt whose protocol version or schema bundle digest differs from the pin is refused. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_preflight_receipt.py:67` `"quarantined receipt uses another protocol"` | SEC-159 |
| BT-REQ-0461 | A runtime config receipt with any non-empty surface attestation is refused because no governed verifier exists. | IMPLEMENTED | `tests/unit/test_codex_runtime_config.py::test_caller_constructible_surface_digests_never_grant_dynamic_surfaces` | SEC-159 |
| BT-REQ-0462 | `/readyz` and `boltrig doctor --production` report the same Codex posture from one shared projection. | IMPLEMENTED-UNTESTED | `boltrig/api/doctor_codex.py:47` `"from boltrig.observability.codex_admission import codex_release_posture"` | - |
| BT-REQ-0463 | The `core` release mode plus an enabled trusted Codex lane is a hard `release_mode_conflict` failure in both readiness and doctor. | IMPLEMENTED-UNTESTED | `boltrig/api/codex_readiness.py:60` `"if release_posture == \"conflict\":"` | - |
| BT-REQ-0464 | Codex runtime config is composed from a private revalidated snapshot and rejects any non-empty ambient override mapping. | IMPLEMENTED | `tests/unit/test_codex_runtime_config_adversarial.py::test_compose_uses_a_private_snapshot_after_validation` | SEC-159 |
| BT-REQ-0465 | The composed config is ASCII, at most 768 KiB, and must match its receipt on digest, byte count and every re-rendered field. | IMPLEMENTED | `tests/unit/test_codex_runtime_config.py::test_composes_exact_secretless_read_only_config_and_receipt` | SEC-159 |
| BT-REQ-0466 | The App Server argv pins the security-critical config leaves and is derived from the receipt rather than stored beside it. | IMPLEMENTED | `tests/unit/test_codex_runtime_config_argv.py`; `boltrig/fleet/infrastructure/codex_runtime_config.py:202` `"Deliberately NOT a stored field."` | SEC-159 |
| BT-REQ-0467 | The cell environment is exactly `CODEX_HOME`, `HOME`, `LANG`, `LC_ALL`, `PATH` plus an optional supervisor-managed auth token; additions may extend it but never override a base key, capped at eight entries of bounded printable ASCII. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_cell_policy.py:390` `"environment additions never override the base"` | SEC-184 |
| BT-REQ-0468 | The rendered config disables 19 dynamic Codex features, with `multi_agent` the only variable one, and sets `approval_policy = "never"`, `sandbox_mode = "read-only"`, `web_search = "disabled"`, `history.persistence = "none"` and `shell_environment_policy.inherit = "none"`. | IMPLEMENTED | `tests/unit/test_codex_managed_config.py`; `boltrig/fleet/infrastructure/codex_runtime_config_toml.py:40` `"CODEX_RUNTIME_DISABLED_FEATURES"` | SEC-159 |
| BT-REQ-0469 | A root-owned mode-0444 managed config on the read-only image mount pins the cell-invariant security leaves, and it is documented that naming a leaf defends that leaf but not the table it sits in. | IMPLEMENTED | `deploy/codex/managed_config.toml:20` `"Naming a leaf defends that leaf. It does"` | SEC-159 |
| BT-REQ-0470 | The kernel-tools lane is selected by a capability whose `supported_skills` contains `*`, or by an explicit `force_kernel_tools` from the permanent seam. | IMPLEMENTED | `boltrig/fleet/runtime_resolver.py:369` `"force_kernel_tools or \"*\" in (capability.supported_skills or [])"` | SEC-184 |
| BT-REQ-0471 | The lane's tool ceiling is the tenant permission set intersected with the run grants, derived through the same `offer_candidates` the kernel MCP face uses. | IMPLEMENTED | `tests/integration/test_codex_kernel_tools_mcp.py::test_the_ceiling_compiler_and_the_mcp_face_derive_one_tool_set` | SEC-184 |
| BT-REQ-0472 | Verb ids become Codex wire names through one sanitizer, are unique, sorted, bounded to 128 names of at most 128 characters, and a malformed ceiling is refused rather than cleaned up. | IMPLEMENTED | `tests/unit/test_codex_kernel_tools_phase.py`; `boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:210` `"kernel tools must be an exact tuple of strings"` | SEC-184 |
| BT-REQ-0473 | A ceiling over the 128-name bound, or an empty ceiling, falls back to the read-only phase with a logged reason and never silently truncates. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_kernel_tools_phase.py:194` `"falling back to the read-only phase"`; bounded: `rg -n "admissible_kernel_tool_names" tests/` finds no dedicated fallback test | - |
| BT-REQ-0474 | The run-scoped kernel MCP token reaches the cell only as a child-process environment variable, never in the config file, argv, a repr or a pickle. | IMPLEMENTED | `tests/unit/test_codex_runtime_config_mcp.py::test_the_token_never_reaches_the_config_receipt_repr_or_argv` | SEC-184 |
| BT-REQ-0475 | The run-scoped token is revoked and the scope discarded in a `finally` whether the phase ran, failed or never started. | IMPLEMENTED | `tests/unit/test_codex_kernel_tools_lane.py::test_kernel_tools_run_revokes_and_discards_on_failure` | SEC-184 |
| BT-REQ-0476 | The per-cell model proxy strips Codex built-in tools and unlisted verbs from the request, flattens the MCP namespace, and reattaches the namespace on in-ceiling response function calls. | IMPLEMENTED | `tests/integration/test_codex_kernel_tools_mcp.py::test_the_proxy_offers_exactly_the_granted_wire_names` | SEC-184 |
| BT-REQ-0477 | A model-call body the proxy cannot parse raises `ToolCeilingViolation` rather than being forwarded, because an unverifiable tool set is not an admitted one. | IMPLEMENTED | `tests/unit/test_model_proxy_tool_ceiling.py::test_an_unparseable_body_is_refused_rather_than_forwarded`; [`boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py:101`](../../../boltrig/fleet/infrastructure/model_proxy_tool_ceiling.py) `"raise ToolCeilingViolation(\"model-call body is not parseable JSON\")"` | - |
| BT-REQ-0478 | An admitted cell's observed MCP inventory must be exactly zero servers on the read-only lane and exactly one on the kernel-tools lane. | IMPLEMENTED | `tests/unit/test_codex_kernel_tools_lane.py::test_preflight_mcp_count_is_bound_to_the_admitted_lane` | SEC-184 |
| BT-REQ-0479 | Both shipped Codex lanes compile a native-subagent policy whose defaults and ceiling are all zero. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_read_only_phase.py:113` `"NativeSubagentPolicy(NativeSubagentLimits(), NativeSubagentLimits())"` | SEC-159 |
| BT-REQ-0480 | `CodexPhaseAdmission` refuses any policy that is not read-only, that declares enabled runtime tools, or whose native subagent limits are not `(0, 0, 0)`. | IMPLEMENTED | `boltrig/fleet/infrastructure/codex_runtime_admission.py:134` `"native agents lack enforceable runtime controls"` | SEC-159 |
| BT-REQ-0481 | The only native-collaboration tool namespace the wire gate admits is `multi_agent_v1`, with a fixed five-tool set. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_native_collaboration_wire.py:12` `"CODEX_NATIVE_COLLAB_NAMESPACE_NAME = \"multi_agent_v1\""` | - |
| BT-REQ-0482 | A Codex run without both a run id and a workspace id degrades with `no_read_only_phase_scope` rather than fabricating a scope. | IMPLEMENTED | `tests/unit/test_codex_runtime.py::test_run_degrades_without_run_scope` | - |
| BT-REQ-0483 | Any lifecycle exception in a Codex turn degrades with `codex_turn_failed:<ExceptionClass>` and never raises into the caller. | IMPLEMENTED | `tests/unit/test_codex_runtime.py::test_run_degrades_and_never_raises_on_lifecycle_error` | - |
| BT-REQ-0484 | A turn that produced no assistant text degrades as `codex_empty_output`, or `codex_empty_output_after_error` when runtime errors were observed, and still reports the tokens the turn consumed. | IMPLEMENTED | `tests/unit/test_codex_runtime.py::test_empty_output_after_a_runtime_error_is_distinguished` | - |
| BT-REQ-0485 | A turn's tool steps are capped at 16 by default; `BOLTRIG_CODEX_MAX_TOOL_STEPS` overrides it, an explicit `0` disables the cap, and an unparsable or negative value keeps the default. | IMPLEMENTED | `tests/unit/test_codex_tool_step_cap.py::test_no_cap_means_the_operator_chose_unbounded` | - |
| BT-REQ-0486 | Exceeding the tool-step budget interrupts the turn before degrading, so a runaway loop stops burning wall clock. | IMPLEMENTED | `tests/unit/test_codex_tool_step_cap.py::test_a_looping_turn_is_interrupted_and_degrades_with_its_spend` | - |
| BT-REQ-0487 | Reasoning, messages and plans are not tool steps; only the seven declared tool item types count against the budget. | IMPLEMENTED | `tests/unit/test_codex_tool_step_cap.py::test_thinking_is_not_a_step_and_completion_under_budget_returns` | - |
| BT-REQ-0488 | A degraded turn reports what the provider was already paid, including the input/output split, so a failed turn is not refunded in full. | IMPLEMENTED | `tests/unit/test_codex_token_usage.py::test_degrade_carries_what_the_turn_consumed` | - |
| BT-REQ-0489 | A failed assignment model-binding registration degrades with `codex_model_binding_failed:<Class>` and the binding is discarded in `finally`. | IMPLEMENTED | `tests/unit/test_codex_runtime.py::test_trusted_model_binding_is_cleaned_when_lifecycle_never_consumes_it` | SEC-WRK-02 |
| BT-REQ-0490 | A permanent profile resolves its runtime with `pinned_policy=True`, and any exception yields a typed `permanent_runtime_unavailable:<Class>` degrade with the budget reservation refunded. | IMPLEMENTED-UNTESTED | `boltrig/fleet/permanent_runtime.py:328` `"reason=f\"permanent_runtime_unavailable:{type(exc).__name__}\","`; `tests/unit/test_permanent_runtime.py` exists but no marker binds this branch | - |
| BT-REQ-0491 | A pinned permanent profile whose resolved endpoint model differs from the composed Codex model raises `PinnedRuntimePolicyUnavailable` rather than running a different model. | IMPLEMENTED-UNTESTED | `boltrig/fleet/runtime_resolver.py:250` `"the composed Codex model does not satisfy the pinned profile"` | - |
| BT-REQ-0492 | The Codex execution ledger stack is off by default and constructs nothing, parking `None` on the platform object. | IMPLEMENTED | `tests/unit/test_codex_execution.py::test_codex_ledger_defaults_off_and_builds_no_stack` | SEC-170 |
| BT-REQ-0493 | `shadow_admit` records at most one execution-neutral `RootEngineDecision` per root run and swallows every failure so it can never break a live turn. | IMPLEMENTED | `tests/integration/test_codex_shadow_root_admission.py::test_shadow_admit_failure_is_swallowed_and_turn_completes` | SEC-172 |
| BT-REQ-0494 | The only rollout policy any composition constructs is generation 1 in mode OFF, and the router short-circuits to `LEGACY` before reading compatibility or workload. | IMPLEMENTED | `tests/unit/test_codex_rollout_routing.py`; `boltrig/api/codex_execution.py:57` `"_SCAFFOLD_POLICY = CodexRolloutPolicy(generation=1, mode=CodexRolloutMode.OFF)"` | SEC-170 |
| BT-REQ-0495 | `AssignmentAdmission.admit` is constructed but never called from any production path. | SCAFFOLDED | bounded: `rg -n "assignment_admission" boltrig/`, 2026-08-24, three hits all in `api/codex_execution.py`; `boltrig/observability/codex_admission.py:76` `"\"assignment_admission\": \"inactive_never_called\""` | SEC-170 |
| BT-REQ-0496 | `SupervisedCodexPhaseCellProvider` is never constructed outside tests and is not the production cell provider. | DEAD | bounded: `rg -n "SupervisedCodexPhaseCellProvider" .`, 2026-08-24, hits only in `tests/unit/test_codex_runtime_admission*.py`, the class definition and its `__all__` entry | - |
| BT-REQ-0497 | Cell stderr is classified against a seven-token allowlist of Codex-internal strings and only the stable labels are surfaced, never the surrounding text. | IMPLEMENTED | `tests/unit/test_codex_stdio_transport.py`; `boltrig/fleet/infrastructure/codex_stdio_transport.py:55` `"Never returns any surrounding"` | - |
| BT-REQ-0498 | The kernel MCP endpoint the tools lane points at is read from `BOLTRIG_CODEX_MCP_URL`, then `BOLTRIG_MCP_URL`, defaulting to `http://kernel:8000/v1/mcp`, and is validated before wiring. | IMPLEMENTED-UNTESTED | `boltrig/fleet/runtime_resolver.py:374` `"os.environ.get(\"BOLTRIG_CODEX_MCP_URL\")"` | - |
| BT-REQ-0499 | The read-only lane's cell id, cell root and workspace path are deterministic functions of the assignment id, so the adapter and the provisioner agree without a round trip. | IMPLEMENTED-UNTESTED | `boltrig/fleet/infrastructure/codex_read_only_phase.py:66` `"tag = hashlib.sha256(assignment.assignment_id.encode(\"utf-8\")).hexdigest()[:16]"` | - |
