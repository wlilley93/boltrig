# Risks harvested from SPEC-04-fleet-runtime-codex.md

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

---

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

---

RISK: **`AgentResult.degrade` returns `ok=True`, so a caller that checks only `ok` treats a
degrade as a success.** The marker is `degraded` and the reason is nested under
`output["_degraded"]` ([`boltrig/fleet/result.py:132`](../../../boltrig/fleet/result.py)
`"ok=True,"`). The `_project_agent_result` path in `spawn_entrypoints` re-adds a default
`_degraded` marker when one is missing
([`boltrig/fleet/spawn_entrypoints.py:146`](../../../boltrig/fleet/spawn_entrypoints.py)
`"output.setdefault(\"_degraded\", {\"reason\": \"degraded\"})"`), which is a symptom of the
same shape.

---

RISK: **`UnavailableRuntime` inherits `runtime = "python-script"` from `ScriptRuntime` rather
than reporting the requested name.** Any consumer reading `runtime.runtime` (as
`PermanentAgentRuntime.__init__` does for the capability, and as any future observability code
might) sees a script runtime where a Codex lane was requested; the requested name survives only
inside `output["_degraded"]["runtime"]`
([`boltrig/fleet/runtime.py:61`](../../../boltrig/fleet/runtime.py)
`"class UnavailableRuntime(ScriptRuntime):"`).

---

RISK: **The Codex degrade contract, the tool-step cap and the token-usage accounting bind no
invariant.** 25 tests across three files, one invariant marker between them (bounded:
`rg -n "pytest.mark.invariant" tests/unit/test_codex_runtime.py tests/unit/test_codex_tool_step_cap.py
tests/unit/test_codex_token_usage.py`, 2026-08-24, pinned tree). `P9`, the doctrine these tests
enforce, is bound to two tests in unrelated areas
([`tests/invariants.yaml:421`](../../../tests/invariants.yaml)
`"tests/kernel/test_ratelimit_degraded.py::test_degraded_mode_when_backend_down"`), so deleting
the Codex degrade tests would not move any catalogue number.

---

RISK: **`BOLTRIG_CODEX_MAX_TOOL_STEPS=0` silently uncaps a runaway tool loop.** The code calls
this "the operator's call, never a fallback"
([`boltrig/fleet/codex_runtime_support.py:58`](../../../boltrig/fleet/codex_runtime_support.py)
`"disables the cap"`), and it is read from the ambient process environment at
`CodexRuntime` construction rather than from validated settings
([`boltrig/fleet/codex_runtime_support.py:66`](../../../boltrig/fleet/codex_runtime_support.py)
`"raw = os.environ.get(_MAX_TOOL_STEPS_ENV, \"\").strip()"`). No doctor or readiness check
reports that the cap is off (bounded: `rg -n "BOLTRIG_CODEX_MAX_TOOL_STEPS" boltrig/ scripts/`,
2026-08-24, two hits, both in that module).

---

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

---

RISK: **`SupervisedCodexPhaseCellProvider` is dead in the production composition.** It is
constructed only in tests (bounded: `rg -n "SupervisedCodexPhaseCellProvider" .`, 2026-08-24,
pinned tree: 8 hits in two test files, one class definition, one `__all__` entry). It runs a
weaker path than the live provider: no posture wall, no boundary proof, no ingress, no model
proxy, and `CODEX_APP_SERVER_BASE_ARGUMENTS` with no per-cell pins
([`boltrig/fleet/infrastructure/codex_runtime_admission.py:250`](../../../boltrig/fleet/infrastructure/codex_runtime_admission.py)
`"arguments=CODEX_APP_SERVER_BASE_ARGUMENTS"`). A future caller reaching for it would get a cell
with none of the guarantees this spec describes.

---

RISK: **`_prove_the_host_can_enforce_the_cell_wall` shells out to the pinned Codex binary at
process composition time**, with a default 60-second timeout and a maximum of 300
([`boltrig/fleet/infrastructure/codex_sandbox_engagement.py:50`](../../../boltrig/fleet/infrastructure/codex_sandbox_engagement.py)
`"DEFAULT_PROBE_TIMEOUT_SECONDS = 60.0"`). Three subprocess runs of a real Codex binary sit on the
API's startup path whenever `BOLTRIG_CODEX_TRUSTED` is set.

---

RISK: **The trusted composition's model-proxy grant store is in-memory**, so grants do not
survive a process restart and are not visible to a sibling replica
([`boltrig/api/codex_trusted.py:199`](../../../boltrig/api/codex_trusted.py)
`"grant_store = MemoryModelProxyGrantStore()"`). A Postgres adapter exists
(`postgres_model_proxy_grants.py`) and is not wired here.

---

RISK: **`api/codex_execution.py` reads `store._pool`, a private attribute**, and says so
([`boltrig/api/codex_execution.py:153`](../../../boltrig/api/codex_execution.py)
`"pool = store._pool"`). It is guarded only by the flag being off by default.

---

RISK: **G3 is open and recorded as open**: the cell's `config.toml` carries `auth.command` and
lives in a `CODEX_HOME` the cell uid owns, so under the shared-uid posture a sibling can rewrite
it; the mitigation is a refusal to run two cells at once, not isolation
([`boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py:40`](../../../boltrig/fleet/infrastructure/codex_trusted_proxy_provider.py)
`"so G3 is OPEN"`). The managed config defends named leaves but not the tables they sit in:
"an attacker-supplied `[mcp_servers.attacker]` with its own `command` survives"
([`deploy/codex/managed_config.toml:19`](../../../deploy/codex/managed_config.toml)
`"[mcp_servers.attacker] with its own \"command\" survives"`).

---

RISK: **Native-subagent limits are detection tripwires, not admission control, and the code says
so.** A notification arrives after the App Server has begun the action, so exceeding a limit
terminates the phase but cannot prove the action was prevented
([`boltrig/fleet/infrastructure/codex_runtime_events.py:72`](../../../boltrig/fleet/infrastructure/codex_runtime_events.py)
`"a notification arrives after App Server has begun the action"`). The compensating control is
that both shipped lanes set the ceiling to zero.

---

RISK: **`make python-quality`, the CI-enforced set, does not include `codex-pin-health`**
([`Makefile:228`](../../../Makefile) `"python-quality: invariants lint architecture structure
vds-ledgers codex-protocol"`). The binary-presence check runs only in `make check`, which the
Makefile itself describes as "NOT what CI enforces"
([`Makefile:223`](../../../Makefile)).

---

RISK: **`README.md` and `docs/architecture/engine-components.md` both claim retired runtimes were
removed including "binaries"**
([`docs/architecture/engine-components.md:314`](../../../docs/architecture/engine-components.md)
`"There is no feature flag, provider client, subprocess wrapper, binary, or plugin that can
revive a retired lane."`). That claim holds for the pinned tree, but the same tree does ship a
mechanism that downloads and stages Codex binaries at release time for three platforms
([`scripts/stage_desktop_codex.py:24`](../../../scripts/stage_desktop_codex.py) `"PLATFORMS = {"`),
so a reader should not generalise the sentence to "this repository contains no agent binaries".
