---
area: 13 Process composition, bootstrap and the CLI surfaces
id-block: BT-REQ-1300..BT-REQ-1399
referent-commit: 19bcae7fa81663fe8998377c86451ba08fb16e48
referent-branch: origin/main
author-agent: brownfield-spec-agent-13
date: 2026-08-24
---

# SPEC-13: Process composition, bootstrap and the CLI surfaces

## Bound of this reading

Every file in the owned scope was read in full, line by line, at the pinned
commit: `app_composition.py` (145 lines), `asgi.py` (41), `bootstrap.py` (652),
`platform_bootstrap.py` (175), `device_bootstrap.py` (26),
`camera_bootstrap.py` (23), `birth_profile_startup.py` (48),
`agent_tool_bootstrap.py` (39), `cli.py` (303), `chat_cli.py` (377),
`chat_cli_gateway.py` (32), `chat_cli_http.py` (39), `worker.py` (445),
`initiate.py` (261), `hitl_resume_bridge.py` (30),
`model_runtime_composition.py` (34), `logging_config.py` (58),
`audit_verify.py` (109). Total 2837 lines, exhaustive, no sampling.

Collaborators outside the scope were read only where a contract crosses the
boundary and only to the depth needed to state that contract: `boot_guards.py`,
`kernel/app.py::create_app`, `kernel/held_call.py`, `kernel/hitl.py::_fire_resume`,
`kernel/workflow_trigger_finalization.py`, `config/birth_profile.py`,
`config/manifest_runtime.py`, `config/environment.py`, `fleet/workers.py::register_workers`,
`fleet/hatchet_bootstrap.py`, `fleet/hatchet_worker.py`, `store/schema.sql`
(the three tables this area writes), `docker-compose.yml`, the two Dockerfiles,
`genesis.sh`, `Makefile`, `docs/decisions/0018-held-write-resume.md`,
`tests/invariants.yaml`, and the eleven test modules that exercise this area.
Claims about those files are scoped to the ranges cited and nothing wider.

Not read, and therefore not claimed on: `auth_routes.py`, `auth_password_routes.py`,
`auth_recovery_routes.py`, `auth_selection.py`, `desktop_session_auth.py`,
`doctor*.py`, `readiness*.py`, `mint_token.py`, `config_validate.py` beyond its
`main()` contract, `fleet_health.py` beyond its docstring contract. Those belong
to other areas of this corpus; this spec records only how the CLI reaches them.

## 2. Purpose

This subsystem is the composition root: the only place in Boltrig where a
kernel, a fleet, an identity resolver and a set of platform services are
assembled into a running operating-system process. It ships four serving
entrypoints (the ASGI app, the fleet worker, the durable Hatchet worker, and the
`boltrig` command line) and enforces the rule that each of them constructs at
most ONE trusted Codex provider and loads at most ONE manifest snapshot, then
injects that exact pair into every spawner it owns. It also owns the answer-side
bridge that turns a human HITL decision into an executed durable write
(decision 0018), the shell-level audit-chain re-derivation, and the one declared
logging configuration every process shares.

## 3. Boundaries

**What it owns.** Process construction and ordering. The manifest snapshot for
the life of a process. The trusted-Codex config object and the Bifrost model
catalogue instance. The kernel/spawner/chat/platform factories handed to
`create_app`. The HITL answer notifier. The janitor loops of the fleet worker.
The `boltrig` argparse table and its dispatch. The founding-owner ceremony. The
`audit-verify` exit-code contract. Root logging.

**What it must not touch.** It implements no policy. Every registration it makes
goes through `kernel.register_adapter`, which is the ordinary chokepoint, and
registering a verb grants nothing:
[`boltrig/api/bootstrap.py:173`](../../../boltrig/api/bootstrap.py) `"registering it does NOT grant it (the tenant"`.
It never resolves a credential; MCP bearers bind to the credential seam by
reference:
[`boltrig/api/bootstrap.py:164`](../../../boltrig/api/bootstrap.py) `"MCP bearers bind to the seam (SEC-04/05)"`.

**The import rule and who enforces it.** AGENTS.md states the layering rule:
`kernel/` and `models/` import nothing from `fleet/`
([`AGENTS.md:41`](../../../AGENTS.md) `"Respect the import boundary"`).
`boltrig/api/` is the layer that is ALLOWED to import both, and that is why the
HITL bridge takes its fleet-side legs as injected callables rather than importing
them into the kernel:
[`boltrig/api/bootstrap.py:324`](../../../boltrig/api/bootstrap.py) `"The kernel side only sees the injected callables; it"`.
The architecture gate enforces an allow-list for `domain`, `ports`,
`application` and `models`
([`scripts/check_architecture.py:30`](../../../scripts/check_architecture.py) `"_LAYER_IMPORTS = {"`)
and a deny-list for `kernel`
([`scripts/check_architecture.py:57`](../../../scripts/check_architecture.py) `"_KERNEL_ROOT = (\"boltrig\", \"kernel\")"`).
No rule in that gate names `boltrig.api` at all, so this area's own imports are
ungated by construction (bounded: read of `_LAYER_IMPORTS`, `_LAYER_ROOTS`,
`_KERNEL_ROOT` and `_KERNEL_FORBIDDEN` at `scripts/check_architecture.py:30-58`,
2026-08-24, pinned tree).

**The structural ratchet.** `bootstrap.py` is over the 400-line floor and carries
a dated exemption pinned to its exact measurement:
[`docs/refactoring/structural-exemptions.json`](../../../docs/refactoring/structural-exemptions.json)
`"boltrig/api/bootstrap.py"` with `"max_file_lines": 652` and
`"expires": "2026-12-31"`. `worker.py` (445) and `initiate.py` (261, with a
99-line `_run`) carry their own entries in the same file. `cli.py` and
`chat_cli.py` are under the floor and carry none.

## 4. Objects and contracts

### 4.1 The process model-runtime snapshot

`compose_process_model_runtime` is the single function every serving process
calls first. It returns a 4-tuple and nothing else may re-derive its members:

| member | type | meaning |
| --- | --- | --- |
| `manifest_path` | `str \| None` | the file the snapshot came from, or None |
| `manifest` | `FleetManifest \| None` | the ONE snapshot for this process |
| `codex_config` | `dict[str, object] \| None` | the ONE trusted Codex provider, None when off |
| catalogue | `BifrostModelCatalogue` | the ONE model catalogue instance |

[`boltrig/api/model_runtime_composition.py:17`](../../../boltrig/api/model_runtime_composition.py)
`"tuple[str | None, Any, dict[str, object] | None, BifrostModelCatalogue]"`.

Order inside it is load-bearing and is itself an invariant: find the manifest,
load it, `export_runtime_environment(manifest)`, THEN build the Codex config and
the catalogue, so both see the same gateway route
([`boltrig/api/model_runtime_composition.py:26`](../../../boltrig/api/model_runtime_composition.py)
`"manifest_path = find_manifest()"`, and the reason at :22 `"both see the same
gateway route for the life of this process."`). The export only fills values
that are absent, so explicit process environment stays authoritative
([`boltrig/config/manifest_runtime.py:25`](../../../boltrig/config/manifest_runtime.py)
`"if base_url and \"BOLTRIG_MODEL_GATEWAY_URL\" not in target:"`).

### 4.2 Manifest discovery

`_find_manifest` reads `BOLTRIG_MANIFEST` LIVE rather than at import, then falls
back to three well-known paths in order:
[`boltrig/api/bootstrap.py:49`](../../../boltrig/api/bootstrap.py)
`"_MANIFEST_CANDIDATES = ("` with `/app/manifest.yaml`, `manifest.yaml`,
`manifest.example.yaml`, and the live read at
[`boltrig/api/bootstrap.py:61`](../../../boltrig/api/bootstrap.py)
`"os.environ.get(\"BOLTRIG_MANIFEST\", \"\")"`. `manifest.example.yaml` is a
tracked file in the repo root, so a source-tree run with no manifest still boots
from the example rather than from the demo seed.

`_MANIFEST_UNSET` is a sentinel object distinct from `None`, because `None` is a
legitimate snapshot value meaning "no manifest exists":
[`boltrig/api/bootstrap.py:54`](../../../boltrig/api/bootstrap.py)
`"_MANIFEST_UNSET = object()"`.

### 4.3 The factories handed to `create_app`

`compose_api_app` returns `create_app(...)` with four injected callables and one
resolver:

- `kernel_factory` (no args, async) built by `_make_kernel_factory`
- `spawner_factory(kernel)` a lambda closing over the snapshot's routing policy
- `principal_resolver` chosen once from the snapshot
- `chat_factory(kernel)` and `platform_factory(kernel)`

[`boltrig/api/app_composition.py:115`](../../../boltrig/api/app_composition.py)
`"return create_app("`.

`create_app` runs all four inside the ASGI lifespan, on the serving loop, so
loop-bound resources (the asyncpg pool) attach to the loop that handles requests:
[`boltrig/kernel/app.py:242`](../../../boltrig/kernel/app.py)
`"that the lifespan runs on the SERVING loop so loop-bound"`, and the
lifespan body at [`boltrig/kernel/app.py:276`](../../../boltrig/kernel/app.py)
`"if not hasattr(app.state, \"kernel\"):"`.

### 4.4 The platform service bag

`_build_platform_services(kernel, ...)` returns a dict that becomes
`app.state.platform`. Keys, all constructed once per boot:

| key | value | citation anchor |
| --- | --- | --- |
| `admin` | `AdminConfig(store, tenant, path=manifest_path)` | `"admin = AdminConfig(kernel.store,"` |
| `bifrost_models` | the process catalogue | `"\"bifrost_models\": model_catalogue,"` |
| `eval` | `EvalRunner(kernel, spawner, workflows=...)` | `"eval_runner = EvalRunner(kernel, spawner"` |
| `spawner` | the platform spawner | `"spawner = build_spawner("` |
| `codex_execution` | shadow stack or None | `"codex_execution = build_codex_execution_stack("` |
| `workflows` | `WorkflowLibrary` | `"workflows = WorkflowLibrary(kernel.store"` |
| `password_reset_notifier` / `_probe` | passed through from `asgi.py` | `"\"password_reset_notifier\": password_reset_notifier,"` |
| `status` | `StackToolStatusProvider(ModelGatewayStatusProvider())` | `"status = StackToolStatusProvider("` |
| `readiness` | `ReadinessService(...)` | `"\"readiness\": ReadinessService("` |
| policy keys | from `_platform_policy_inputs` | see below |

[`boltrig/api/platform_bootstrap.py:118`](../../../boltrig/api/platform_bootstrap.py)
`"return {"`.

`_platform_policy_inputs` is deliberately narrow: the projection receives
composition TRUTH, never provider details. It publishes only a boolean for
whether the trusted provider is configured, plus the non-secret model id:
[`boltrig/api/platform_bootstrap.py:37`](../../../boltrig/api/platform_bootstrap.py)
`"Projection receives composition truth only, never provider details."` and
[`boltrig/api/platform_bootstrap.py:40`](../../../boltrig/api/platform_bootstrap.py)
`"Provider topology, URLs and the upstream key remain absent."`.

### 4.5 The held call (decision 0018)

The record a paused write is resumed FROM. Two rows, neither of them the params
in plain JSON:

- a `run_checkpoints` row on the ROOT run, step `held:<call_id>`, status
  `paused`, carrying the approval request id
  ([`boltrig/kernel/held_call.py:49`](../../../boltrig/kernel/held_call.py)
  `"HELD_STEP_PREFIX = \"held:\""`);
- the canonical call `{noun, verb, params, ctx}` sealed as a run-scoped
  credential under its own kind
  ([`boltrig/kernel/held_call.py:13`](../../../boltrig/kernel/held_call.py)
  `"credentials.HELD_CALL_KIND"`).

Three redeemer lanes are named from the record, never stored beside it:
`LANE_CALLER`, `LANE_HELD_WRITE`, `LANE_INTERPRETER`
([`boltrig/kernel/held_call.py:70`](../../../boltrig/kernel/held_call.py)
`"LANE_CALLER = \"caller\""`). This spec owns only the answer-side bridge that
claims the `held_write` lane.

### 4.6 The birth-profile receipt

One bounded startup snapshot per process kind. Fields are opaque digests, never
values:
[`boltrig/config/birth_profile.py:168`](../../../boltrig/config/birth_profile.py)
`"def make_birth_profile_receipt("`. The per-boot instance identity rotates on a
pid change so a pre-forked server cannot publish a duplicate:
[`boltrig/config/birth_profile.py:137`](../../../boltrig/config/birth_profile.py)
`"A pre-fork server inherits module state.  Rotate in the child"`.

## 5. Control flow

### 5.1 ASGI process construction, in order

1. `configure_logging()` runs BEFORE any other boltrig import.
   [`boltrig/api/asgi.py:18`](../../../boltrig/api/asgi.py) `"configure_logging()"`.
   Failure branch: an unreadable `BOLTRIG_LOG_LEVEL` falls back to INFO rather
   than silencing the process
   ([`boltrig/api/logging_config.py:45`](../../../boltrig/api/logging_config.py)
   `"return level if isinstance(level, int) else logging.INFO"`).
2. `active_addons()` resolves the configured add-ons at boot.
   [`boltrig/api/asgi.py:26`](../../../boltrig/api/asgi.py) `"_ADDONS = active_addons()"`.
   Failure branch: an unregistered name RAISES `AddonError` and the process does
   not start
   ([`boltrig/addons/__init__.py:167`](../../../boltrig/addons/__init__.py)
   `"names unregistered addon(s)"`). The stated reason is that the alternative is
   an intermittent mid-turn failure long after the deploy
   ([`boltrig/api/asgi.py:24`](../../../boltrig/api/asgi.py)
   `"reached from the adapter's tool listing - i.e. mid-turn, intermittently"`).
3. `compose_password_reset_delivery()` builds the notifier/probe pair.
   [`boltrig/api/asgi.py:36`](../../../boltrig/api/asgi.py) `"_PASSWORD_RESET_NOTIFIER, _PASSWORD_RESET_PROBE"`.
4. `build_app(...)` is called at IMPORT and returns the FastAPI object.
   [`boltrig/api/asgi.py:37`](../../../boltrig/api/asgi.py) `"app = build_app("`.
   `build_app` is a pure dependency-injection facade over `compose_api_app`
   ([`boltrig/api/bootstrap.py:635`](../../../boltrig/api/bootstrap.py)
   `"from boltrig.api.app_composition import compose_api_app"`).
5. Inside `compose_api_app`, at import time: the addons snapshot is taken, the
   model runtime snapshot is composed, `spawn_rules` and `sensitive_endpoint_id`
   are read off the snapshot, the chat wiring pair is built, the platform factory
   is bound, and the kernel factory is closed over the same objects.
   [`boltrig/api/app_composition.py:74`](../../../boltrig/api/app_composition.py)
   `"manifest_path, manifest, codex_config, model_catalogue = ("`.
   Failure branch: a manifest that the shipping loader rejects raises here and
   the process fails at import, which is what `boltrig config-validate` exists to
   pre-empt.
6. At LIFESPAN, `kernel_factory()` runs `build_kernel_async(...)` with the
   snapshot injected, then overlays the desired fleet state, then publishes the
   birth receipt.
   [`boltrig/api/app_composition.py:26`](../../../boltrig/api/app_composition.py)
   `"kernel = await build_kernel_async("`.
   Failure branch: if a manifest EXISTS but its effective overlay cannot be
   computed, the kernel is returned and NO receipt is published, so a startup
   receipt is never a claim about a manifest generation that was not applied
   ([`boltrig/api/app_composition.py:34`](../../../boltrig/api/app_composition.py)
   `"if manifest is not None and effective_manifest is None:"`, and the warning
   at :138 `"startup receipt not published"`).
7. `spawner_factory(kernel)`, `chat_factory(kernel)` and `platform_factory(kernel)`
   run in the same lifespan block
   ([`boltrig/kernel/app.py:281`](../../../boltrig/kernel/app.py)
   `"app.state.spawner = spawner_factory(built) if spawner_factory else spawner"`).
8. On shutdown the kernel is closed
   ([`boltrig/kernel/app.py:289`](../../../boltrig/kernel/app.py)
   `"await active_kernel.aclose()"`).

### 5.2 `build_kernel_async`, in order

1. `refuse_default_audit_key_in_prod()` FIRST, before any store connection.
   [`boltrig/api/bootstrap.py:419`](../../../boltrig/api/bootstrap.py)
   `"refuse_default_audit_key_in_prod()"`. Failure branch: fatal `RuntimeError`
   under a production signal with a placeholder key
   ([`boltrig/api/boot_guards.py:60`](../../../boltrig/api/boot_guards.py)
   `"FATAL: BOLTRIG_AUDIT_HMAC_KEY is unset/default"`); a warning, every boot,
   without a signal ([`boltrig/api/boot_guards.py:72`](../../../boltrig/api/boot_guards.py)
   `"audit chain is using the IN-SOURCE default HMAC key"`).
2. `store = await build_store()`.
   [`boltrig/api/bootstrap.py:420`](../../../boltrig/api/bootstrap.py) `"store = await build_store()"`.
3. Shared rate-limit counter and event relay from `REDIS_URL`.
   [`boltrig/api/bootstrap.py:423`](../../../boltrig/api/bootstrap.py)
   `"counter = build_counter(os.environ.get(\"REDIS_URL\"))"`. The relay is told
   whether this is production so it can refuse a production-local fallback
   ([`boltrig/api/bootstrap.py:426`](../../../boltrig/api/bootstrap.py)
   `"production=production_signal() is not None,"`).
4. Snapshot resolution. If the caller passed `_MANIFEST_UNSET` the manifest is
   re-read from disk here (the standalone convenience path); otherwise the
   injected snapshot is used verbatim.
   [`boltrig/api/bootstrap.py:429`](../../../boltrig/api/bootstrap.py)
   `"if manifest_snapshot is _MANIFEST_UNSET:"`.
5. Sensitive-routing coherence check. If the caller injected a
   `sensitive_endpoint_id` that disagrees with the snapshot, boot REFUSES.
   [`boltrig/api/bootstrap.py:440`](../../../boltrig/api/bootstrap.py)
   `"sensitive model routing changed during process composition"`.
6. Kernel construction. With a manifest the kernel is given the blocking-verb
   set, the approval timeout and the development posture; without one it gets
   only store, counter and relay.
   [`boltrig/api/bootstrap.py:446`](../../../boltrig/api/bootstrap.py)
   `"blocking_verbs=manifest.blocking_verbs(),"`.
7. Hands registry, only when the desktop-hands add-on is on.
   [`boltrig/api/bootstrap.py:450`](../../../boltrig/api/bootstrap.py)
   `"if _desktop_hands_enabled():"`.
8. Seeding: `_seed_from_manifest` or `_seed_default` (section 5.3).
9. `kernel.set_agent_invoker(make_agent_invoker(...))` LAST, carrying the same
   `codex_config`, catalogue and sensitive role.
   [`boltrig/api/bootstrap.py:461`](../../../boltrig/api/bootstrap.py)
   `"kernel.set_agent_invoker("`.

### 5.3 Seeding, manifest path, in exact order

[`boltrig/api/bootstrap.py:278`](../../../boltrig/api/bootstrap.py) `"async def _seed_from_manifest("`:

1. `apply_manifest(kernel, manifest)` (tenant permissions, adapters, agents).
2. `provision_builtin_integration_catalogue`.
3. memory, knowledge, distill, each from its own manifest section.
4. `_register_control_plane` (governed config amendment).
5. `register_agent_support` (section 5.7).
6. `_register_channel_send` with the manifest, so the diversion resolver and the
   network posture ride the adapter.
7. `register_device_actions`, `register_camera_actions`.
8. familiar, only when `BOLTRIG_EMOTION=1`
   ([`boltrig/api/bootstrap.py:289`](../../../boltrig/api/bootstrap.py)
   `"if os.environ.get(\"BOLTRIG_EMOTION\", \"\").strip() == \"1\":"`).
9. desktop hands, only when the add-on is on.
10. `_register_consumed_mcp` for `mcp.consume` entries, each INERT pending review.
11. `_register_web_fetch` BEFORE the rehydrate. This ordering is deliberate and
    the reason is on the record: rehydrate skips already-registered ids, so the
    old order warned about the `web` row every boot and then registered it live
    two lines later
    ([`boltrig/api/bootstrap.py:301`](../../../boltrig/api/bootstrap.py)
    `"a pure ordering artifact that read"`).
12. `_rehydrate_store_adapters`.
13. `load_skills_dir`, best-effort.

Failure branches: step 13 catches every exception and warns, because a bad skill
file must not stop boot
([`boltrig/api/bootstrap.py:312`](../../../boltrig/api/bootstrap.py)
`"a bad skill file should not stop boot"`). Steps 1 to 12 are unguarded: a
failing adapter registration aborts the boot.

### 5.4 Rehydrating store-persisted adapters

Four outcomes per row, all of them explicit
([`boltrig/api/bootstrap.py:223`](../../../boltrig/api/bootstrap.py)
`"async def _rehydrate_store_adapters("`):

| condition | outcome |
| --- | --- |
| the id was already registered this boot | skip silently (`"the manifest registered this id this boot already"`) |
| `rehydrate_adapter_instance` returns an adapter | INFO, live (`"rehydrated %s adapter '%s' from its store row"`) |
| a generated adapter with no valid projection | WARNING, store-only (`"delete and re-generate it"`) |
| a non-MCP row not declared in the manifest | WARNING, store-only (`"is not declared in the manifest"`) |
| an MCP row with no persisted url | WARNING, store-only (`"cannot be "` / `"rehydrated; delete and re-register it"`) |

The fourth row's wording is itself a recorded correction: the previous text read
as a defect and caused a misdiagnosis
([`boltrig/api/bootstrap.py:260`](../../../boltrig/api/bootstrap.py)
`"wording misread as a defect (beelink, 2026-08-21)"`).

### 5.5 The fleet worker, in order

[`boltrig/api/worker.py:362`](../../../boltrig/api/worker.py) `"async def _run() -> None:"`:

1. `configure_logging()` and `active_addons()` at MODULE IMPORT, mirroring the
   ASGI entrypoint ([`boltrig/api/worker.py:46`](../../../boltrig/api/worker.py)
   `"configure_logging()"`; :58 `"_ADDONS = active_addons()"`). The reason both
   processes must resolve add-ons is stated: the pinned kernel-tools birth
   profile is composed from the active add-ons, so a worker whose environment
   differs would compile a different profile version than the kernel attests
   ([`boltrig/api/worker.py:55`](../../../boltrig/api/worker.py)
   `"would compile a different profile version than the kernel"`).
2. `compose_process_model_runtime(...)`, the same call the API makes.
3. `build_kernel_async(...)` with the snapshot, explicitly async so there is no
   nested `asyncio.run`
   ([`boltrig/api/worker.py:381`](../../../boltrig/api/worker.py)
   `"# async build (no nested asyncio.run)"`).
4. `register_workers(kernel)` selects the executor and the choice is logged with
   its durability ([`boltrig/api/worker.py:385`](../../../boltrig/api/worker.py)
   `"fleet worker started (%s, durable=%s)"`).
5. `_manifest_spawn_context` overlays the desired fleet state onto the snapshot.
   Failure branch: on ANY exception the overlay is abandoned, `manifest` becomes
   None, the default org is used, and `desired_overlay_applied` stays False
   ([`boltrig/api/worker.py:285`](../../../boltrig/api/worker.py)
   `"manifest load failed (%s); using the default org"`).
6. `build_org(...)` builds the delegation pump, with the Codex shadow-admission
   stack built at this composition root.
7. `_publish_birth_profile_startup(process_kind="fleet", ...)`.
8. `record_permanent_fleet_startup_observation` ONLY when the overlay applied
   ([`boltrig/api/worker.py:416`](../../../boltrig/api/worker.py)
   `"if desired_overlay_applied:"`). This is what stops a default-org boot from
   reading as an applied desired hierarchy.
9. `_start_background_tasks(...)` returns a 7-tuple of tasks-or-None.
10. `await pump.run_forever(tenant, interval=5.0)`.
11. `finally`: cancel and gather every started task, then `kernel.aclose()`
    ([`boltrig/api/worker.py:431`](../../../boltrig/api/worker.py)
    `"await _stop_background_tasks(tasks)"`).

`main()` swallows `KeyboardInterrupt` into a clean log line
([`boltrig/api/worker.py:440`](../../../boltrig/api/worker.py)
`"except KeyboardInterrupt:"`).

### 5.6 The HITL answer bridge, in order

`wire_hitl_resume` installs exactly one notifier on the kernel's HITL manager
([`boltrig/api/bootstrap.py:354`](../../../boltrig/api/bootstrap.py)
`"kernel.hitl.set_resume_notifier(_on_answer)"`). Inside `_on_answer`, four legs
run in this order:

1. **Held-write replay.** `resume_held_write_route(kernel, resume_held_write, request)`.
   [`boltrig/api/bootstrap.py:331`](../../../boltrig/api/bootstrap.py)
   `"await resume_held_write_route(kernel, resume_held_write, request)"`.
   Guards, all fail-closed to "do nothing":
   - no injected resume, not an APPROVAL, or no `run_id` returns immediately
     ([`boltrig/api/hitl_resume_bridge.py:17`](../../../boltrig/api/hitl_resume_bridge.py)
     `"if resume is None or request.type != HITLType.APPROVAL or not request.run_id:"`);
   - a verb whose finalization would discard a one-time webhook secret is left
     to the origin caller
     ([`boltrig/api/hitl_resume_bridge.py:20`](../../../boltrig/api/hitl_resume_bridge.py)
     `"if await approval_requires_origin_finalization(kernel.store, request):"`);
   - `held_write_is_waiting` must be true, which is false when ANOTHER lane also
     paused on this request, so the interpreter and the held-write lanes are
     mutually exclusive
     ([`boltrig/kernel/held_call.py:250`](../../../boltrig/kernel/held_call.py)
     `"Mutually exclusive with the durable/interpreter route by the reserved prefix"`).
   Failure branch: any exception is caught and warned; the answer stands
   ([`boltrig/api/hitl_resume_bridge.py:30`](../../../boltrig/api/hitl_resume_bridge.py)
   `"held-write resume failed"`).
2. **Durable approval event.** When an executor is injected and the request has a
   run, the scoped approval event is pushed with the recorded decision
   ([`boltrig/api/bootstrap.py:335`](../../../boltrig/api/bootstrap.py)
   `"await executor.push_event("`). Failure branch: caught and warned
   ("resume is best-effort; the answer stands (P9)").
3. **Work-item requeue.** When a pump is injected and the request names a work
   item ([`boltrig/api/bootstrap.py:349`](../../../boltrig/api/bootstrap.py)
   `"await pump.requeue(request.tenant_id, request.work_item_id)"`). Failure
   branch: caught and warned.
4. **Reuse-signal harvest.** `_harvest_hitl_signal` turns an APPROVAL verdict into
   an endorsement or a block through the governed reweight-only path
   ([`boltrig/api/bootstrap.py:358`](../../../boltrig/api/bootstrap.py)
   `"Turn a HITL verdict into a reuse signal"`). Failure branch: caught at DEBUG,
   "a harvest fault never voids it (P9)".

Exactly-once is not this bridge's job: it belongs to the ANSWERED to CONSUMED
CAS ([`boltrig/api/bootstrap.py:325`](../../../boltrig/api/bootstrap.py)
`"Exactly-once execution of the gated verb is"`), which is why a duplicate
delivery is harmless and is proven so by test.

**Where the bridge is wired, and with what.** Three production call sites, and
each carries a DIFFERENT subset of legs:

| process | call site | executor | pump | resume_held_write |
| --- | --- | --- | --- | --- |
| ASGI API | [`boltrig/api/platform_bootstrap.py:108`](../../../boltrig/api/platform_bootstrap.py) `"wire_hitl_resume(kernel, executor=executor, resume_held_write=resume_held_write)"` | yes | NO | yes |
| fleet worker | [`boltrig/api/worker.py:340`](../../../boltrig/api/worker.py) `"wire_hitl_resume(kernel, executor=executor)"` | yes | no | no |
| hatchet worker | [`boltrig/fleet/hatchet_bootstrap.py:109`](../../../boltrig/fleet/hatchet_bootstrap.py) `"wire_hitl_resume(kernel, pump=pump)"` | no | yes | no |

Bounded: `rg -n "wire_hitl_resume" boltrig/ tests/`, 2026-08-24, pinned tree;
every other hit is a test or a docstring reference.

### 5.7 Agent tool bootstrap

`register_agent_support(kernel, tenant_id)` registers four adapters and seeds one
durable identity, and it runs on BOTH seed paths: the demo seed
([`boltrig/api/bootstrap.py:124`](../../../boltrig/api/bootstrap.py)
`"await register_agent_support(kernel, _DEFAULT_TENANT)"`) and the manifest seed
([`boltrig/api/bootstrap.py:285`](../../../boltrig/api/bootstrap.py)
`"await register_agent_support(kernel, manifest.tenant_id)"`):

1. `build_skill_shelf_adapter(kernel.store)` (the progressive-disclosure shelf);
2. `build_work_read_adapter(kernel.store)` (scoped Work board reads);
3. `build_agent_messages(kernel.store, events=kernel.events)` (peer messaging);
4. `build_chat_present(events=kernel.events)` (chat presentation).

[`boltrig/api/agent_tool_bootstrap.py:21`](../../../boltrig/api/agent_tool_bootstrap.py)
`"await kernel.register_adapter(tenant_id, build_skill_shelf_adapter(kernel.store))"`.

Then, if the tenant has no named agents, a `general` script agent is upserted as
the intake default
([`boltrig/api/agent_tool_bootstrap.py:27`](../../../boltrig/api/agent_tool_bootstrap.py)
`"if not await kernel.store.list_named_agents(tenant_id):"`).

**Progressive disclosure, precisely.** Two distinct mechanisms exist and only one
is registered here.

- The SKILL shelf, which this module registers. `skill.search` returns
  lightweight descriptions only and never the `prompt_fragment` body; that is
  named as the progressive-disclosure step
  ([`boltrig/skills/shelf.py:6`](../../../boltrig/skills/shelf.py)
  `"progressive disclosure, not every body in context"`, and :13 `"NEVER the
  prompt_fragment body. This is the progressive-"`). `skill.load` returns
  `tool_grants` as DATA and grants nothing
  ([`boltrig/skills/shelf.py:23`](../../../boltrig/skills/shelf.py)
  `"Load returns the skill's"` ... `"as DATA (what the skill wants), it does"`).
- The TOOL offer, which this area does NOT own. Ranking and budgeting of the
  verbs an agent is offered lives in `boltrig/kernel/tool_disclosure.py` and is
  reached from `boltrig/kernel/mcp_tools_list.py`
  ([`boltrig/kernel/mcp_tools_list.py:49`](../../../boltrig/kernel/mcp_tools_list.py)
  `"page = tool_disclosure.offer_page(candidates, rt.grants, rt.skills, cursor)"`).
  Its claims (subset of what grants admit, disclosure is not deauthorisation,
  fail-closed inputs) are pinned in
  [`tests/unit/test_tool_disclosure.py:1`](../../../tests/unit/test_tool_disclosure.py)
  `"the pure tool-disclosure offer (progressive disclosure, slice 1)"`. The
  composition root touches none of it.

### 5.8 Device and camera actions

Both are conditional on this process being able to SIGN a lease. No signer means
the verbs are not registered at all, so a kernel that cannot sign never
advertises the capability:
[`boltrig/api/device_bootstrap.py:16`](../../../boltrig/api/device_bootstrap.py)
`"signer = DeviceLeaseSigner.from_environment()"` and :139
`"device action verbs disabled (lease signing key unavailable)"`;
[`boltrig/api/camera_bootstrap.py:17`](../../../boltrig/api/camera_bootstrap.py)
`"camera lease verbs disabled (lease signing key unavailable)"`.

### 5.9 `audit-verify`, in order

[`boltrig/api/audit_verify.py:32`](../../../boltrig/api/audit_verify.py)
`"async def _verify(tenant_id: str, from_seq: int = 0)"`:

1. Read `DATABASE_URL`, else `BOLTRIG_DATABASE_URL`. Absent: return `(2, "no
   DATABASE_URL: cannot verify, and cannot call that success")`.
2. Connect a `PostgresStore` with `apply_schema=False`. Unreachable: return
   `(2, "store unreachable: ...")`
   ([`boltrig/api/audit_verify.py:46`](../../../boltrig/api/audit_verify.py)
   `"unreachable store is \"could not look\", not \"fine\""`).
3. If `--from-seq > 1`, read the row BEFORE the segment and use its hash as
   `seed_prev`. No such row: return `(2, "no row at seq ... to seed the segment
   from")`. Otherwise build the SEGMENT ONLY banner naming the unchecked range
   ([`boltrig/api/audit_verify.py:63`](../../../boltrig/api/audit_verify.py)
   `"SEGMENT ONLY: rows 1..{from_seq - 1} were NOT CHECKED."`).
4. `writer.verify(tenant_id, start_after=max(0, from_seq - 1), seed_prev=seed)`.
5. `finally: await store.close()`.
6. Append the retired-epoch note either way
   ([`boltrig/api/audit_verify.py:73`](../../../boltrig/api/audit_verify.py)
   `"retired key epoch(s), boundaries"`).
7. Exit 0 on verify, 1 on a break with the first bad seq named, and the failure
   message states both causes: an altered chain OR a key rotated without
   recording `BOLTRIG_AUDIT_HMAC_RETIRED`
   ([`boltrig/api/audit_verify.py:83`](../../../boltrig/api/audit_verify.py)
   `"Either the chain was altered, or a key was"`).

`main()` writes to stderr when the code is non-zero and stdout when it is zero
([`boltrig/api/audit_verify.py:108`](../../../boltrig/api/audit_verify.py)
`"file=sys.stderr if code else sys.stdout"`).

### 5.10 `boltrig initiate`, in order

[`boltrig/api/initiate.py:65`](../../../boltrig/api/initiate.py) `"async def _run("`:

1. Normalise and validate the email; exit 2 on a bad one.
2. `validate_password_strength`; exit 2 on `WeakPassword`.
3. `build_store()`, then `set_current_tenant(tenant)` BEFORE any RLS-scoped read
   ([`boltrig/api/initiate.py:89`](../../../boltrig/api/initiate.py)
   `"set_current_tenant(tenant)  # bind before any RLS-scoped read/write"`).
4. List users; if ANY has a role in `{superadmin, org-admin, admin}`, print and
   exit 3, touching nothing
   ([`boltrig/api/initiate.py:96`](../../../boltrig/api/initiate.py)
   `"refusing to run twice."`).
5. Upsert the owner with `role=superadmin`, `scope={"all": True}`,
   `source="initiate"` and `must_change_password=True`
   ([`boltrig/api/initiate.py:110`](../../../boltrig/api/initiate.py)
   `"must_change_password=True,"`).
6. `seed_user_onboarding`, then `set_password_credential` with an argon2id hash.
7. `ensure_default_org`, `add_org_member`, deterministic workspace id
   `ws_<slug>`, `create_workspace` if absent, `add_workspace_member(role=owner)`.
8. Audit `auth.initiate` keys-only: email, role, org, workspace. Never the
   password ([`boltrig/api/initiate.py:146`](../../../boltrig/api/initiate.py)
   `"Audit the owner seed keys-only (D8): the email, never the password."`).
9. `finally`: close the store if it has a `close`.

`initiate()` resolves the secret `--password` then `BOLTRIG_INIT_PASSWORD` then
an interactive double prompt, and exits 2 on a mismatch
([`boltrig/api/initiate.py:175`](../../../boltrig/api/initiate.py)
`"secret = password or os.environ.get(\"BOLTRIG_INIT_PASSWORD\")"`).

### 5.11 `boltrig set-password`, in order

[`boltrig/api/initiate.py:187`](../../../boltrig/api/initiate.py)
`"async def _run_set_password("`. Same email/password validation, then:

1. `get_user`; None means exit 3 with an explicit refusal to create an identity
   ([`boltrig/api/initiate.py:216`](../../../boltrig/api/initiate.py)
   `"it does not create one."`).
2. `set_password_credential`.
3. If `must_change_password` was set, clear it, because rotating the credential
   IS the rotation the clamp demands
   ([`boltrig/api/initiate.py:220`](../../../boltrig/api/initiate.py)
   `"Rotating the credential IS the rotation D7 requires"`).
4. Audit with `actor=HOST_BOUNDARY_ACTOR`, `actor_tier="host"`,
   `on_behalf_of=email`. The recorded reason is that writing `actor=email` made a
   shell holder's reset read as the target's own act
   ([`boltrig/api/initiate.py:224`](../../../boltrig/api/initiate.py)
   `"D6: the actor is the HOST BOUNDARY, never the target user."`).
5. `write_host_boundary_security_event(reason="set_password")`, best-effort by
   design ([`boltrig/api/host_boundary.py:46`](../../../boltrig/api/host_boundary.py)
   `"Best-effort by design."`).

## 6. Data

This area writes three durable shapes and reads a fourth.

### 6.1 `birth_profile_receipts` (written)

[`boltrig/store/schema.sql:804`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS birth_profile_receipts ("`.

| column | constraint |
| --- | --- |
| `tenant_id` | part of the PK |
| `process_kind` | `CHECK (process_kind IN ('api','fleet','hatchet'))` |
| `instance_identity` | `~ '^bi_[a-f0-9]{24}$'` |
| `manifest_generation` | `~ '^mf_[a-f0-9]{24}$'` |
| `addon_set_identity` | `~ '^as_[a-f0-9]{24}$'` |
| `codex_provider_identity` | `cp_off_v1` or `^cp_[a-f0-9]{24}$` |
| `codex_provider_state` | `IN ('off','configured')` |
| `sensitive_role_identity` | `sr_absent_v1` or `^sr_[a-f0-9]{24}$` |
| `sensitive_role_state` | `IN ('absent','configured')` |
| `receipt_kind` | `= 'startup_snapshot'` |
| `observed_at`, `expires_at` | `expires_at <= observed_at + interval '1 hour'` |

PK is `(tenant_id, process_kind, instance_identity)`. The three process kinds in
the CHECK are exactly the three this area publishes: `"api"` from
[`boltrig/api/app_composition.py:38`](../../../boltrig/api/app_composition.py)
`"process_kind=\"api\","`, `"fleet"` from
[`boltrig/api/worker.py:408`](../../../boltrig/api/worker.py)
`"process_kind=\"fleet\","`, and `"hatchet"` from
[`boltrig/fleet/hatchet_bootstrap.py:97`](../../../boltrig/fleet/hatchet_bootstrap.py)
`"process_kind=\"hatchet\","`. There is no fourth kind, so the browser executor
publishes nothing.

Retention: bounded by `expires_at` (the DB caps the TTL at one hour) and by
per-kind pruning at the store seam
([`boltrig/store/birth_profiles.py:131`](../../../boltrig/store/birth_profiles.py)
`"WHERE tenant_id=$1 AND process_kind=$2"`). Encryption: none needed, because
every field is a truncated SHA-256 digest over random boot entropy or a fixed
enum ([`boltrig/config/birth_profile.py:33`](../../../boltrig/config/birth_profile.py)
`"The canonical tree is never persisted, logged or returned."`).

### 6.2 `run_checkpoints` (written by the chokepoint, READ by this area)

[`boltrig/store/schema.sql:435`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS run_checkpoints ("`, PK
`(tenant_id, run_id, step)`. The bridge matches rows whose `step` starts with
`held:` and whose `status` is `paused` and whose `hitl_request_id` equals the
answered request. The `output` column carries at most the root run id, never
params ([`boltrig/kernel/held_call.py:55`](../../../boltrig/kernel/held_call.py)
`"HELD_ROOT_KEY = \"held_run_id\""`).

### 6.3 `credential_refs` (READ by this area, through the seam)

[`boltrig/store/schema.sql:713`](../../../boltrig/store/schema.sql)
`"CREATE TABLE IF NOT EXISTS credential_refs ("`. The held call is sealed here
under a distinct kind so it can never resolve into a verb param. Sealed at rest
as a versioned Fernet envelope
([`boltrig/store/schema.sql:708`](../../../boltrig/store/schema.sql)
`"SEALED at the store"`, the sentence continuing onto the next comment line;
[`boltrig/store/sealing.py:17`](../../../boltrig/store/sealing.py)
`"is a Fernet token (AES-128-CBC + HMAC-SHA256, authenticated) over the"`).

### 6.4 `audit_events` (READ by `audit-verify`, WRITTEN by `initiate`/`set-password`)

`audit-verify` re-derives the chain through `AuditWriter.verify` and never
mutates. `initiate` writes one `auth.initiate` row and `set-password` writes one
`auth.set_password` row plus one security-stream event.

**Migrations.** Runtime boot NEVER applies `schema.sql`. Alembic is the
authoritative upgrade path, and the refusal is explicit and unconditional:
[`boltrig/api/bootstrap.py:93`](../../../boltrig/api/bootstrap.py)
`"Runtime boot never applies the mutable convenience bootstrap."` and the call
at :100 `"apply_schema=False"`. `audit-verify` connects with the same
`apply_schema=False`
([`boltrig/api/audit_verify.py:43`](../../../boltrig/api/audit_verify.py)
`"apply_schema=False,"`). The operator path is `make migrate`
([`Makefile:480`](../../../Makefile) `"migrate: ## Apply the authoritative ordered Alembic migration chain"`).

## 7. Configuration surface

### 7.1 Environment read directly by this area

| variable | default | read at | what breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_LOG_LEVEL` | `INFO` | [`boltrig/api/logging_config.py:33`](../../../boltrig/api/logging_config.py) `"ENV_VAR = \"BOLTRIG_LOG_LEVEL\""` | nothing: an unparseable value falls back to INFO |
| `BOLTRIG_MANIFEST` | unset | [`boltrig/api/bootstrap.py:61`](../../../boltrig/api/bootstrap.py) `"os.environ.get(\"BOLTRIG_MANIFEST\", \"\")"` | a wrong path silently falls through to `manifest.yaml` then `manifest.example.yaml`, so the process boots the EXAMPLE tenant |
| `BOLTRIG_ADDONS` | unset (empty tuple) | [`boltrig/addons/__init__.py:162`](../../../boltrig/addons/__init__.py) `"raw = os.environ.get(ENV_VAR)"` | an unregistered name refuses boot in both the API and the worker |
| `DATABASE_URL` | unset (in-memory store) | [`boltrig/api/bootstrap.py:90`](../../../boltrig/api/bootstrap.py) `"if settings.database_url:"` | unset means an in-memory store, so nothing is durable |
| `BOLTRIG_RLS` | off | [`boltrig/api/bootstrap.py:98`](../../../boltrig/api/bootstrap.py) `"rls = is_truthy(os.environ.get(\"BOLTRIG_RLS\"))"` | RLS off means the pool is not tenant-scoped |
| `REDIS_URL` | unset | [`boltrig/api/bootstrap.py:423`](../../../boltrig/api/bootstrap.py) `"counter = build_counter(os.environ.get(\"REDIS_URL\"))"` | unset means per-process rate-limit windows, a process-local event relay, and no fleet stack-tool heartbeat |
| `BOLTRIG_EVENT_RELAY_NAMESPACE` | `default` | [`boltrig/api/bootstrap.py:427`](../../../boltrig/api/bootstrap.py) `"BOLTRIG_EVENT_RELAY_NAMESPACE\", \"default\""` | two stacks on one Redis cross-talk on run events |
| `BOLTRIG_DESKTOP_HANDS` | off | [`boltrig/api/bootstrap.py:137`](../../../boltrig/api/bootstrap.py) `"is_truthy(os.environ.get(\"BOLTRIG_DESKTOP_HANDS\"))"` | on without a host executor advertises `desktop.*` verbs nothing serves |
| `BOLTRIG_EMOTION` | unset | [`boltrig/api/bootstrap.py:289`](../../../boltrig/api/bootstrap.py) `"BOLTRIG_EMOTION\", \"\").strip() == \"1\""` | strict `== "1"`, so `true` or `yes` silently does nothing on the manifest path |
| `BOLTRIG_PRODUCTION`, `ENV`, `BOLTRIG_ENV`, `APP_ENV` | unset | [`boltrig/config/environment.py:21`](../../../boltrig/config/environment.py) `"explicit = (values.get(\"BOLTRIG_PRODUCTION\") or \"\")"` | with none of them set there is NO production signal, so both boot guards degrade to warnings |
| `BOLTRIG_AUDIT_HMAC_KEY` | in-source placeholder | [`boltrig/api/boot_guards.py:50`](../../../boltrig/api/boot_guards.py) `"key = e.get(\"BOLTRIG_AUDIT_HMAC_KEY\")"` | a placeholder in production refuses boot; without a signal it warns and the chain is forgeable |
| `BOLTRIG_DEV_AUTH` | unset | [`boltrig/api/boot_guards.py:25`](../../../boltrig/api/boot_guards.py) `"def refuse_dev_auth_in_prod("` | set with a production signal refuses boot |
| `BOLTRIG_DATABASE_URL` | unset | [`boltrig/api/audit_verify.py:33`](../../../boltrig/api/audit_verify.py) `"os.environ.get(\"BOLTRIG_DATABASE_URL\")"` | fallback DSN for the verifier only |
| `BOLTRIG_TENANT_ID` | `default` | [`boltrig/api/audit_verify.py:103`](../../../boltrig/api/audit_verify.py) `"default=os.environ.get(\"BOLTRIG_TENANT_ID\", \"default\")"` | the verifier checks the wrong tenant's chain and still exits 0 |
| `BOLTRIG_AUDIT_HMAC_RETIRED` | unset | read by `_retired_epochs`, named at [`boltrig/api/audit_verify.py:84`](../../../boltrig/api/audit_verify.py) `"rotated without recording it in BOLTRIG_AUDIT_HMAC_RETIRED."` | a rotation with no recorded epoch makes a sound chain report exit 1 |
| `BOLTRIG_INIT_PASSWORD` | unset (interactive prompt) | [`boltrig/api/initiate.py:175`](../../../boltrig/api/initiate.py) `"os.environ.get(\"BOLTRIG_INIT_PASSWORD\")"` | leaks into the shell environment of both `initiate` and `set-password` |
| `BOLTRIG_SESSION_TENANT` | `default` | via `load_settings().session_tenant` at [`boltrig/api/cli.py:215`](../../../boltrig/api/cli.py) `"tenant = args.tenant or load_settings().session_tenant or \"default\""` | seats the founding owner in the wrong tenant |
| `BOLTRIG_CLI_TOKEN` | unset | [`boltrig/api/chat_cli.py:30`](../../../boltrig/api/chat_cli.py) `"ENV_TOKEN = \"BOLTRIG_CLI_TOKEN\""` | absent and with no config file, `boltrig chat` exits 2 |
| `BOLTRIG_CLI_SERVER` | `http://127.0.0.1:8000` | [`boltrig/api/chat_cli.py:31`](../../../boltrig/api/chat_cli.py) `"ENV_SERVER = \"BOLTRIG_CLI_SERVER\""` | the CLI streams a PAT to the wrong host |
| `HOSTNAME` | `fleet-worker` | [`boltrig/api/worker.py:420`](../../../boltrig/api/worker.py) `"os.environ.get(\"HOSTNAME\") or \"fleet-worker\""` | the permanent-fleet observation is labelled with a shared name |
| `BOLTRIG_DEVICE_LEASE_SIGNING_KEY` | unset | [`boltrig/kernel/device_crypto.py:97`](../../../boltrig/kernel/device_crypto.py) `"encoded = os.environ.get(\"BOLTRIG_DEVICE_LEASE_SIGNING_KEY\", \"\").strip()"` | unset means `device.*` and `camera.*` verbs are not registered at all; a malformed value is treated as unset, silently |
| `BOLTRIG_CODEX_LEDGER` | off | [`boltrig/api/codex_execution.py:115`](../../../boltrig/api/codex_execution.py) `"Construct the Codex execution stack behind"` | off constructs no admission stack, so chat and pump build with `codex_execution=None` |
| `BOLTRIG_REQUIRE_DURABLE` | off | [`boltrig/fleet/workers.py:198`](../../../boltrig/fleet/workers.py) `"is_truthy(os.environ.get(\"BOLTRIG_REQUIRE_DURABLE\"))"` | off means a durable-engine failure silently falls back to the local executor in every process this area starts |
| `BOLTRIG_BIRTH_PROFILE_TTL_SECONDS` | 300, clamped to [30, 3600] | [`boltrig/config/birth_profile.py:157`](../../../boltrig/config/birth_profile.py) `"os.environ.get(\"BOLTRIG_BIRTH_PROFILE_TTL_SECONDS\")"` | a bad value is clamped, never fatal |

### 7.2 Janitor intervals (fleet worker only)

Every loop is off when its interval is `<= 0`, and the worker LOGS which choice
it made, so "off" is a decision on the record rather than silence
([`boltrig/api/worker.py:176`](../../../boltrig/api/worker.py)
`"\"off\" is a decision on the record rather than the silence it used to be."`).

| variable | default | loop | source of the default |
| --- | --- | --- | --- |
| `BOLTRIG_AUDIT_ANCHOR_INTERVAL` | 86400.0 | `audit-anchor-janitor` | [`boltrig/fleet/anchor.py:65`](../../../boltrig/fleet/anchor.py) `"DEFAULT_INTERVAL_SECONDS = 86_400.0  # daily"` |
| `BOLTRIG_HITL_EXPIRY_INTERVAL` | 60.0 | `hitl-expiry-janitor` | [`boltrig/kernel/hitl_expiry.py:60`](../../../boltrig/kernel/hitl_expiry.py) `"DEFAULT_INTERVAL_SECONDS = 60.0"` |
| `BOLTRIG_AUDIT_OUTBOX_INTERVAL` | 60.0 | `audit-outbox-janitor` | [`boltrig/kernel/audit_outbox.py:41`](../../../boltrig/kernel/audit_outbox.py) `"DEFAULT_INTERVAL_SECONDS = 60.0"` |
| `BOLTRIG_RETENTION_INTERVAL` | 3600.0 | `retention-janitor` | [`boltrig/fleet/retention.py:59`](../../../boltrig/fleet/retention.py) `"DEFAULT_INTERVAL_SECONDS = 3600.0"` |
| `BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL` | 15.0 | `workflow-scheduler` | [`boltrig/workflows/scheduler_cron.py:14`](../../../boltrig/workflows/scheduler_cron.py) `"DEFAULT_INTERVAL_SECONDS = 15.0"` |
| (manifest only) `memory.ingest.on_session_end` | off | `session-distillation` | [`boltrig/api/worker.py:222`](../../../boltrig/api/worker.py) `"session distillation disabled (memory.ingest.on_session_end)"` |
| (`REDIS_URL` presence) | off | `fleet-stack-tool-heartbeat` | [`boltrig/api/worker.py:324`](../../../boltrig/api/worker.py) `"fleet stack-tool heartbeat not started (REDIS_URL not configured)"` |

The retention WINDOW is a manifest value, not an env var:
`privacy.retention_days`, default 30 when the manifest sets none
([`boltrig/fleet/retention.py:57`](../../../boltrig/fleet/retention.py)
`"DEFAULT_RETENTION_DAYS = 30"`), while `manifest.example.yaml` ships 365
([`manifest.example.yaml:350`](../../../manifest.example.yaml) `"retention_days: 365"`).

### 7.3 Manifest keys this area reads

| key | consumed by |
| --- | --- |
| `tenant_id` | every seed, every receipt, the janitor tenant |
| `models.sensitive_endpoint` | injected into every spawner and coherence-checked in `build_kernel_async` |
| `spawn_rules` | every spawner |
| `hitl.approval_timeout_seconds` | `Kernel(...)` construction |
| `blocking_verbs()` | `Kernel(...)` construction |
| `development_posture` | `Kernel(...)` construction |
| `chat` | the API chat factory and the platform chat config |
| `privacy` | platform policy inputs and the retention window |
| `network` | `channel.send` and `web.fetch` registration |
| `locale_default`, `timezone_default` | platform user defaults |
| `identity` | `select_principal_resolver` |
| `section("memory"\|"knowledge"\|"distill"\|"mcp")` | the manifest seed path |
| `section("runtimes")`, `section("browser_cli")` | `export_runtime_environment` |
| `extra.memory.ingest.on_session_end` | the worker distillation sweep |

### 7.4 Environment this area WRITES

`export_runtime_environment` sets, only when absent:
`BOLTRIG_MODEL_GATEWAY_URL`, `BOLTRIG_MODEL_GATEWAY_TTL`,
`BOLTRIG_MODEL_GATEWAY_HEALTH`, `BOLTRIG_MODEL_GATEWAY_HEALTH_PATH`,
`BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT`, `BOLTRIG_MODEL_PROFILES`,
`BOLTRIG_BROWSER_CLOUD_POLICY`
([`boltrig/config/manifest_runtime.py:25`](../../../boltrig/config/manifest_runtime.py)
`"if base_url and \"BOLTRIG_MODEL_GATEWAY_URL\" not in target:"` through :50).

## 8. PROCESS

### 8.1 The shipped process inventory

`docker-compose.yml` runs four boltrig python entrypoints:

| service | command | citation |
| --- | --- | --- |
| `kernel` | `uvicorn boltrig.api.asgi:app --host 0.0.0.0 --port 8000` | [`docker-compose.yml:154`](../../../docker-compose.yml) `"command: [\"uvicorn\", \"boltrig.api.asgi:app\""` |
| `fleet-worker` | `python -m boltrig.api.worker` | [`docker-compose.yml:230`](../../../docker-compose.yml) `"command: [\"python\", \"-m\", \"boltrig.api.worker\"]"` |
| `hatchet-worker` | `python -m boltrig.fleet.hatchet_worker` | [`docker-compose.yml:385`](../../../docker-compose.yml) `"command: [\"python\", \"-m\", \"boltrig.fleet.hatchet_worker\"]"` |
| `browser-executor` | `python -m boltrig.fleet.browser_executor` | [`docker-compose.yml:342`](../../../docker-compose.yml) `"command: [\"python\", \"-m\", \"boltrig.fleet.browser_executor\"]"` |

The `hatchet-worker` service exists specifically to close the gap decision 0018
recorded as open. Its comment names that decision:
[`docker-compose.yml:371`](../../../docker-compose.yml)
`"# discovered and recorded in docs/decisions/0018-held-write-resume.md"`. The
decision's own reserved section still reads as though nothing serves the tasks
([`docs/decisions/0018-held-write-resume.md:325`](../../../docs/decisions/0018-held-write-resume.md)
`"stack serves the Hatchet tasks"`), so the decision
document is stale against the tree at this commit and the compose file is right.

### 8.2 Container entrypoint wrapping

The `kernel` image does NOT exec uvicorn directly. Its `ENTRYPOINT` is a
privilege-separation shim
([`deploy/kernel.Dockerfile:232`](../../../deploy/kernel.Dockerfile)
`"ENTRYPOINT [\"/usr/local/bin/python3\", \"/opt/boltrig/kernel-entrypoint.py\"]"`)
which, when the container is uid 0 with a non-empty permitted set, forks a
minimal spawner, drops to uid 10001, PROVES the drop from `/proc`, and only then
execs the command
([`scripts/kernel-entrypoint.py:18`](../../../scripts/kernel-entrypoint.py)
`"Fork a minimal spawner that alone keeps CAP_SETUID/CAP_SETGID,"`). The
unprivileged path is byte-identical to running the command directly
([`scripts/kernel-entrypoint.py:12`](../../../scripts/kernel-entrypoint.py)
`"Unprivileged (today, and every deployment that has not opted in)."`).

The `fleet` image wraps its command in a browser bootstrap that asks the manifest
before touching the filesystem
([`deploy/fleet.Dockerfile:196`](../../../deploy/fleet.Dockerfile)
`"ENTRYPOINT [\"/usr/bin/tini\", \"-g\", \"--\", \"/usr/local/bin/fleet-entrypoint\"]"`,
and [`scripts/fleet-entrypoint.sh:23`](../../../scripts/fleet-entrypoint.sh)
`"if python -m boltrig.fleet.browser_runtime \\"`), then `exec "$@"`.

### 8.3 The `boltrig` console script

Declared as a project script
([`pyproject.toml:126`](../../../pyproject.toml) `"boltrig = \"boltrig.api.cli:main\""`)
and, in the kernel image, ALSO hand-written as a 5-line shim that inserts `/app`
onto `sys.path`, with the reason recorded
([`deploy/kernel.Dockerfile:171`](../../../deploy/kernel.Dockerfile)
`"is load-bearing, not defensive"`). The build smoke-tests
it in the same layer (`/usr/local/bin/boltrig --help >/dev/null`).

### 8.4 The command inventory

Thirteen subcommands, all declared with `required=True`
([`boltrig/api/cli.py:33`](../../../boltrig/api/cli.py) `"sub = parser.add_subparsers(dest=\"cmd\", required=True)"`),
every one of them dispatched:

| command | dispatches to | exit contract |
| --- | --- | --- |
| `serve` | `uvicorn.run(...)` ([`boltrig/api/cli.py:243`](../../../boltrig/api/cli.py) `"uvicorn.run(\"boltrig.api.asgi:app\", host=args.host, port=args.port)"`) | 0 when uvicorn returns; host defaults to `127.0.0.1` ([`boltrig/api/cli.py:38`](../../../boltrig/api/cli.py) `"default=\"127.0.0.1\","`) |
| `worker` | `boltrig.api.worker.main()` ([`boltrig/api/cli.py:266`](../../../boltrig/api/cli.py) `"worker_main()"`) | always 0 |
| `fleet-health` | `fleet_health.main()` | 0 ok or not-applicable, 1 stale/degraded |
| `audit-verify` | `audit_verify.main(argv)` | 0 verifies, 1 does not, 2 could not look |
| `initiate` | `initiate.initiate()` | 0 seated, 2 bad input, 3 owner already exists |
| `set-password` | `initiate.set_password()` | 0 set, 2 bad input, 3 no such user |
| `mint-token` | `mint_token.mint_token()` | owned by the identity area |
| `smoke` | `runpy.run_path(scripts/smoke.py)` | 0, or 2 when the script is absent |
| `check-invariants` | `runpy.run_path(scripts/check_invariants.py)` | 0, or 2 when the script is absent |
| `chat` | `chat_cli.run(args)` | 0 clean exit, 2 no token / unreachable gateway / clean error |
| `doctor` | `doctor.run_doctor(...)` | `report.exit_code` |
| `config-validate` | `config_validate.main(path)` | 0 accepted, 2 rejected |
| `version` | prints `boltrig.__version__` | 0 |

The identity trio resolves its tenant identically (flag, else session tenant,
else `default`) precisely so the router stays thin
([`boltrig/api/cli.py:215`](../../../boltrig/api/cli.py)
`"tenant = args.tenant or load_settings().session_tenant or \"default\""`).

`_repo_script` resolves `scripts/<name>` three directories up from `cli.py`
([`boltrig/api/cli.py:27`](../../../boltrig/api/cli.py) `"path = os.path.join(here, \"scripts\", name)"`).
Neither Dockerfile copies `scripts/` into the image (bounded:
`grep -n "^COPY\|^ADD" deploy/kernel.Dockerfile deploy/fleet.Dockerfile`,
2026-08-24; only `scripts/kernel-entrypoint.py` and `scripts/fleet-entrypoint.sh`
are copied, each to a fixed absolute path). `boltrig smoke` and
`boltrig check-invariants` therefore print `"script for '<cmd>' not found"` and
exit 2 inside every shipped container; they work only from a source checkout.

### 8.5 Founding ceremony

`genesis.sh` is the one-shot founder ceremony and it calls `initiate` inside the
kernel container ([`genesis.sh:160`](../../../genesis.sh)
`"if compose exec -T kernel boltrig initiate \\"`). Its own header states the
idempotency contract that `boltrig initiate` is one-shot and fail-closed
([`genesis.sh:14`](../../../genesis.sh) `"is one-shot fail-closed (refuses twice)"`).
The guide repeats it
([`docs/guide/00-getting-started.md:51`](../../../docs/guide/00-getting-started.md)
`"This step is one-shot: it refuses to run twice once an owner exists."`).

### 8.6 Operator procedures that touch this area

| procedure | command | citation |
| --- | --- | --- |
| bring the stack up | `make up` | [`Makefile:38`](../../../Makefile) `"up: ## Build + start the whole stack"` |
| bring it up with the TLS overlay | `make secure-up` | [`Makefile:41`](../../../Makefile) `"secure-up: ## Start with the TLS / encrypted-at-rest overlay"` |
| apply migrations | `make migrate` | [`Makefile:480`](../../../Makefile) `"migrate: ## Apply the authoritative ordered Alembic migration chain"` |
| static readiness | `make doctor ARGS="--production"` | [`Makefile:478`](../../../Makefile) `"$(PY) -m boltrig.api.cli doctor --env-file .env --manifest manifest.yaml"` |
| offline smoke | `make smoke` | [`Makefile:472`](../../../Makefile) `"$(PY) scripts/smoke.py"` |
| invariant binding gate | `make invariants` | [`Makefile:475`](../../../Makefile) `"$(PY) scripts/check_invariants.py"` |
| manifest pre-flight against the candidate image | `boltrig config-validate /m.yaml` | [`docs/PROD-CUTOVER-RUNBOOK.md:143`](../../../docs/PROD-CUTOVER-RUNBOOK.md) `"boltrig config-validate /m.yaml"` |
| production doctor inside the signed image | `validate_release_runtime.py` | [`scripts/validate_release_runtime.py:198`](../../../scripts/validate_release_runtime.py) `"\"boltrig.api.cli\","` |
| mint an operator PAT for a lane smoke | `boltrig.api.cli mint-token` | [`scripts/lane-smoke.sh:29`](../../../scripts/lane-smoke.sh) `"$COMPOSE exec -T kernel python -m boltrig.api.cli mint-token"` |
| re-derive the audit chain | `boltrig audit-verify --tenant T` | [`boltrig/api/cli.py:53`](../../../boltrig/api/cli.py) `"\"audit-verify\","` |

There is no scheduled invocation of `audit-verify` anywhere in the tree. Bounded:
`grep -rn "audit-verify" .` over the pinned tree excluding
`docs/brownfield-spec/`, 2026-08-24. Eight hits, every one of them a declaration,
a documentation row or a test. Two in the module itself
([`boltrig/api/audit_verify.py:89`](../../../boltrig/api/audit_verify.py)
`"argparse.ArgumentParser(prog=\"boltrig audit-verify\")"`), two in the `cli.py`
parser and dispatch, one documentation row
([`docs/claim-inventory.tsv:315`](../../../docs/claim-inventory.tsv)
`"a cron or a probe can re-derive"`), two in the feature ledger
([`tests/worker_feature_ledger.py:844`](../../../tests/worker_feature_ledger.py)
`"\"audit-verify\": _coverage("`), and one test module
([`tests/unit/test_audit_verify_cli.py:1`](../../../tests/unit/test_audit_verify_cli.py)
`"must report the three outcomes DISTINCTLY"`). No cron entry, no systemd timer,
no compose healthcheck.

### 8.7 Gates that read this area's SOURCE, not its behaviour

- `scripts/check_health_claims.py` parses `cli.py`'s dispatch with `ast` and maps
  each subcommand to the module it hands off to, deliberately reading the
  DISPATCH rather than the parser table, because a subcommand can be declared and
  never wired ([`scripts/check_health_claims.py:342`](../../../scripts/check_health_claims.py)
  `"rather than from the parser table, because a subcommand can be declared and"`).
  It also records that `fleet-worker` runs `python -m boltrig.api.worker` and has
  no HTTP listener ([`scripts/check_health_claims.py:63`](../../../scripts/check_health_claims.py)
  `"a delegation pump with no HTTP listener, so there"`).
- `tests/unit/test_logging_is_configured.py::test_both_entrypoints_configure_logging_and_neither_rolls_its_own`
  reads `asgi.py` and `worker.py` as TEXT and asserts each contains
  `configure_logging()` and no `basicConfig`
  ([`tests/unit/test_logging_is_configured.py:96`](../../../tests/unit/test_logging_is_configured.py)
  `"assert \"configure_logging()\" in src, f\"{name} does not configure logging\""`).
- `tests/unit/test_codex_trusted_composition.py::test_every_packaged_build_spawner_call_explicitly_threads_runtime_policy`
  walks every `boltrig/**/*.py` with `ast` and refuses a `build_spawner` call
  that omits `codex_config` or `sensitive_endpoint_id`, asserting at least seven
  such calls exist
  ([`tests/unit/test_codex_trusted_composition.py:828`](../../../tests/unit/test_codex_trusted_composition.py)
  `"assert seen >= 7"`).
- `tests/security/test_worker_feature_ledger.py::test_every_native_command_is_classified_and_registered`
  asserts the CLI subcommand set equals the ledger's classification set
  ([`tests/security/test_worker_feature_ledger.py:185`](../../../tests/security/test_worker_feature_ledger.py)
  `"assert _cli_commands() == set(CLI_COMMAND_FEATURES)"`).
- `scripts/check_structure.py` holds `bootstrap.py`, `worker.py` and
  `initiate.py` to their exact measured sizes with dated exemptions
  ([`scripts/check_structure.py:25`](../../../scripts/check_structure.py)
  `"FILE_LINE_LIMIT = 400"`).

### 8.8 Recovery paths

- **A boot that dies on config.** Run `boltrig config-validate <manifest>` with
  the candidate image. The reason this exists is a real crash-loop from a manifest
  field with no default ([`boltrig/api/config_validate.py:7`](../../../boltrig/api/config_validate.py)
  `"is missing required fields: priority"`).
- **A boot that dies on an add-on name.** The message names the registered set
  ([`boltrig/addons/__init__.py:168`](../../../boltrig/addons/__init__.py)
  `"registered: {', '.join(sorted(_REGISTRY)) or '(none)'}"`).
- **A boot that refuses on the audit key.** Set a real `BOLTRIG_AUDIT_HMAC_KEY`;
  every placeholder the project has ever shipped is rejected
  ([`tests/security/test_audit_key_provisioning.py:33`](../../../tests/security/test_audit_key_provisioning.py)
  `"_SHIPPED_PLACEHOLDERS = ("`).
- **A chain that will not verify below a known break.** Use
  `--from-seq N`, which seeds from row N-1 and PRINTS the unchecked range, so
  skipping is on the record ([`boltrig/api/audit_verify.py:98`](../../../boltrig/api/audit_verify.py)
  `"skipped range, because skipping is exactly how a real break gets missed."`).
- **An approved write that never executed.** The answer-side bridge is idempotent
  and can be re-fired: `HITLManager.refire_resume` is the documented
  reconciliation trigger, and the fleet worker's expiry sweep calls it
  ([`boltrig/kernel/hitl.py:264`](../../../boltrig/kernel/hitl.py)
  `"async def refire_resume(self, tenant_id: str, request_id: str) -> None:"`).
- **A locked-out founding owner.** `boltrig set-password --email ...` from a
  shell on the box, which also discharges the forced-rotation clamp.

## 9. Failure modes and fail-open / fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| default audit HMAC key under a production signal | FAIL-CLOSED (RuntimeError) | [`boltrig/api/boot_guards.py:60`](../../../boltrig/api/boot_guards.py) `"FATAL: BOLTRIG_AUDIT_HMAC_KEY is unset/default"` |
| default audit HMAC key with NO production signal | FAIL-OPEN, loudly | [`boltrig/api/boot_guards.py:72`](../../../boltrig/api/boot_guards.py) `"audit chain is using the IN-SOURCE default HMAC key"`; the comment at :67 admits "a real deployment can reach here" |
| dev auth under a production signal | FAIL-CLOSED | [`boltrig/api/boot_guards.py:32`](../../../boltrig/api/boot_guards.py) `"raise RuntimeError("` |
| no principal resolver configured | FAIL-CLOSED (401 every request) | [`boltrig/api/bootstrap.py:496`](../../../boltrig/api/bootstrap.py) `"authentication is not configured"` |
| `create_app` with no resolver under a production signal | FAIL-CLOSED (refuses to build) | [`boltrig/kernel/app.py:257`](../../../boltrig/kernel/app.py) `"FATAL: create_app() received no principal_resolver"` |
| partial or divergent manifest OIDC trio | FAIL-CLOSED (RuntimeError) | [`tests/security/test_identity_manifest_wiring.py:70`](../../../tests/security/test_identity_manifest_wiring.py) `"with pytest.raises(RuntimeError, match=\"partial\"):"` |
| sensitive-routing mismatch during composition | FAIL-CLOSED (RuntimeError) | [`boltrig/api/bootstrap.py:440`](../../../boltrig/api/bootstrap.py) `"sensitive model routing changed during process composition"` |
| unregistered add-on name | FAIL-CLOSED at import, in BOTH processes | [`boltrig/api/asgi.py:26`](../../../boltrig/api/asgi.py) `"_ADDONS = active_addons()"`, [`boltrig/api/worker.py:58`](../../../boltrig/api/worker.py) `"_ADDONS = active_addons()"` |
| device / camera lease signing key absent | FAIL-CLOSED (verbs not registered) | [`boltrig/api/device_bootstrap.py:18`](../../../boltrig/api/device_bootstrap.py) `"device action verbs disabled (lease signing key unavailable)"` |
| desktop hands add-on off | FAIL-CLOSED (capability not advertised) | [`boltrig/api/bootstrap.py:135`](../../../boltrig/api/bootstrap.py) `"Default OFF: a kernel that does"` |
| consumed MCP servers | FAIL-CLOSED (registered INERT pending review) | [`boltrig/api/bootstrap.py:206`](../../../boltrig/api/bootstrap.py) `"each INERT pending review (SEC-22)"` |
| skills directory load | FAIL-OPEN (warn, continue) | [`boltrig/api/bootstrap.py:312`](../../../boltrig/api/bootstrap.py) `"a bad skill file should not stop boot"` |
| adapter rehydration of an undeclared row | FAIL-CLOSED (store-only, warned) | [`boltrig/api/bootstrap.py:264`](../../../boltrig/api/bootstrap.py) `"manifest adapters: list (or its opt-in flag)"` |
| Hatchet task registration in the API platform factory | FAIL-OPEN (warn, continue) | [`boltrig/api/platform_bootstrap.py:107`](../../../boltrig/api/platform_bootstrap.py) `"log.warning(\"boltrig task registration failed\", exc_info=True)"` |
| API birth receipt when the effective manifest is unavailable | FAIL-CLOSED (no receipt) | [`boltrig/api/app_composition.py:34`](../../../boltrig/api/app_composition.py) `"if manifest is not None and effective_manifest is None:"` |
| birth receipt write failure | FAIL-OPEN (warn, return False) | [`boltrig/api/birth_profile_startup.py:38`](../../../boltrig/api/birth_profile_startup.py) `"except Exception:"` |
| worker manifest overlay failure | FAIL-OPEN to the default org, and refuses to claim parity | [`boltrig/api/worker.py:285`](../../../boltrig/api/worker.py) `"manifest load failed (%s); using the default org"` |
| every HITL resume leg | FAIL-OPEN (warn; the recorded answer stands) | [`boltrig/api/bootstrap.py:345`](../../../boltrig/api/bootstrap.py) `"resume is best-effort; the answer stands (P9)"` |
| resume notifier itself | FAIL-OPEN, silently | [`boltrig/kernel/hitl.py:249`](../../../boltrig/kernel/hitl.py) `"a notifier fault never voids it"` (the handler is a bare `except Exception: pass` at :261) |
| held-write route on a request another lane claimed | FAIL-CLOSED (does nothing) | [`boltrig/kernel/held_call.py:250`](../../../boltrig/kernel/held_call.py) `"Mutually exclusive with the durable/interpreter route by the reserved prefix"` |
| `audit-verify` cannot reach a store | FAIL-CLOSED (exit 2, never 0) | [`boltrig/api/audit_verify.py:20`](../../../boltrig/api/audit_verify.py) `"Exit 2 is deliberately NOT 0."` |
| `initiate` when an owner exists | FAIL-CLOSED (exit 3, writes nothing) | [`boltrig/api/initiate.py:96`](../../../boltrig/api/initiate.py) `"refusing to run twice."` |
| `set-password` for a non-existent user | FAIL-CLOSED (exit 3) | [`boltrig/api/initiate.py:216`](../../../boltrig/api/initiate.py) `"it does not create one."` |
| host-boundary security event write | FAIL-OPEN by design | [`boltrig/api/host_boundary.py:46`](../../../boltrig/api/host_boundary.py) `"Best-effort by design."` |
| `boltrig chat` config file malformed | FAIL-CLOSED (clean error, not "no token") | [`boltrig/api/chat_cli.py:48`](../../../boltrig/api/chat_cli.py) `"error, never a silent fall-through to 'no token configured'."` |
| `boltrig chat` SSE payload malformed | FAIL-OPEN (dropped) | [`boltrig/api/chat_cli.py:74`](../../../boltrig/api/chat_cli.py) `"malformed / non-object payloads are dropped, never fatal."` |
| `boltrig chat` gateway frame malformed | FAIL-OPEN (dropped) | [`boltrig/api/chat_cli_gateway.py:27`](../../../boltrig/api/chat_cli_gateway.py) `"a malformed line is dropped, never fatal"` |
| `boltrig serve` bind address | FAIL-CLOSED (loopback unless explicit) | [`boltrig/api/cli.py:38`](../../../boltrig/api/cli.py) `"default=\"127.0.0.1\","` |
| a bad `BOLTRIG_LOG_LEVEL` | FAIL-OPEN to INFO, deliberately | [`boltrig/api/logging_config.py:39`](../../../boltrig/api/logging_config.py) `"An unreadable value must not silence the process"` |

## 10. What is proven

| invariant | what it binds here | binding test |
| --- | --- | --- |
| `CODEX-COMPOSITION-1` | one provider, one snapshot, injected into every packaged spawner; a source gate on new `build_spawner` calls | `tests/unit/test_codex_trusted_composition.py::test_api_composition_shares_one_codex_config_with_every_factory`, `::test_kernel_uses_the_composition_manifest_snapshot_without_rereading`, `::test_standalone_worker_shares_one_codex_provider_with_its_spawner`, `::test_default_hatchet_bootstrap_shares_one_codex_provider_with_its_spawner`, `::test_every_packaged_build_spawner_call_explicitly_threads_runtime_policy`, `tests/unit/test_model_runtime_composition.py::test_manifest_gateway_is_exported_before_process_model_resources_are_composed`, `tests/unit/test_readiness.py::test_platform_composition_threads_the_manifest_into_readiness` |
| `K-19` | the audit-key boot guard, on every placeholder the project has shipped | `tests/security/test_audit_key_provisioning.py::test_every_shipped_placeholder_is_fatal_under_a_production_signal` and `::test_every_shipped_placeholder_warns_without_a_production_signal` |
| `SEC-60` | dev auth refuses a production signal | `tests/security/test_round_sixteen.py::test_dev_auth_refuses_production_signal` |
| `SEC-135` | `boltrig serve` binds loopback unless `--host` is explicit | `tests/unit/test_cli.py::test_serve_is_loopback_only_unless_host_is_explicit` |
| `SEC-14` | the held write is recorded at the chokepoint, carried out on answer, and only the sealed params can execute it | `tests/security/test_held_write_resume.py::test_a_gated_chat_write_records_the_held_call_at_the_chokepoint`, `::test_answering_the_approval_carries_out_the_held_write`, `::test_only_the_sealed_params_can_execute_the_held_write`, `::test_a_missing_seal_refuses_and_never_guesses_the_call` |
| `NFR-REL-03` | a duplicate resume delivery executes the write exactly once | `tests/security/test_held_write_resume.py::test_delivering_the_resume_twice_executes_the_write_once` |
| `SEC-181` | the held call can never be resolved back into a verb param, and the seal is swept at every terminal | `tests/security/test_held_write_resume.py::test_a_held_call_can_never_be_resolved_back_into_a_verb_param`, `::test_settling_the_hold_retires_the_bearer_the_turn_sealed` |
| `SEC-74` | the fleet worker actually STARTS the retention janitor, and "off" is a decision | `tests/fleet/test_worker_janitors.py::test_the_fleet_worker_starts_the_retention_janitor`, `::test_the_retention_janitor_is_off_only_when_someone_turns_it_off` |
| `SEC-WRK-27` | a default-org boot cannot claim permanent-fleet startup parity | `tests/fleet/test_worker_janitors.py::test_default_org_does_not_claim_permanent_fleet_startup_parity` |
| `US-EXE-05` | executor selection is honest and optionally fail-closed | `tests/integration/test_executor_selection.py::test_require_durable_refuses_to_fall_back` |
| `WRK-06` | every CLI subcommand and every named worker background task carries a lifecycle classification | `tests/security/test_worker_feature_ledger.py::test_every_native_command_is_classified_and_registered`, `::test_every_named_fleet_background_task_is_classified` |
| `SEC-WRK-30` | the trusted provider composition is threaded and a failed overlay cannot claim parity | `tests/unit/test_codex_trusted_composition.py::test_hatchet_failed_manifest_overlay_cannot_claim_startup_parity` |

Tested but NOT bound to any invariant id (each is a finding in its own right, see
RISKS): the whole of `tests/unit/test_logging_is_configured.py`, the whole of
`tests/unit/test_audit_verify_cli.py`, the whole of `tests/unit/test_chat_cli.py`,
`tests/security/test_identity_manifest_wiring.py`,
`tests/security/test_set_password.py`,
`tests/security/test_operator_seat_ratchet.py`, and
`tests/security/test_first_party_login.py::test_initiate_is_idempotent_and_refuses_twice`
(bounded: `grep -n "invariant" <each file>`, 2026-08-24, pinned tree).

## 11. RISKS

RISK: `boltrig audit-verify` exists, is tested, and is scheduled by NOTHING. Its
own docstring says it exists so a cron can re-derive the chain
([`boltrig/api/audit_verify.py:1`](../../../boltrig/api/audit_verify.py)
`"from a shell, so a cron or a"`), yet no compose service, healthcheck,
Makefile target, deploy unit or genesis phase invokes it (bounded:
`grep -rn "audit-verify" .` over the pinned tree excluding
`docs/brownfield-spec/`, 2026-08-24). This is the same "a ledger nobody
re-derives" shape the file was written to close, one level up.

RISK: The API's chat factory RE-READS the manifest from disk at lifespan time,
which is a second manifest load in a process the composition invariant says
loads at most one snapshot
([`boltrig/api/bootstrap.py:590`](../../../boltrig/api/bootstrap.py)
`"chat_cfg = load_manifest(manifest_path).chat"`). The Hatchet path takes the
same value off the snapshot instead
([`boltrig/fleet/hatchet_bootstrap.py:92`](../../../boltrig/fleet/hatchet_bootstrap.py)
`"chat_config=manifest.chat if manifest is not None else None,"`), so the two
processes can disagree about `chat` if the file changes between the API's import
and its lifespan.

RISK: That same re-read swallows every exception into `pass`, so a manifest that
became unreadable after import silently downgrades chat to the default
`ChatConfig()` rather than failing
([`boltrig/api/bootstrap.py:591`](../../../boltrig/api/bootstrap.py)
`"except Exception:"`, and the default at
[`boltrig/fleet/chat.py:91`](../../../boltrig/fleet/chat.py)
`"self._cfg = chat_config if chat_config is not None else ChatConfig()"`).

RISK: The `pump` leg of the HITL answer bridge is never wired in the process
that ANSWERS. The API passes `executor` and `resume_held_write` but no pump
([`boltrig/api/platform_bootstrap.py:108`](../../../boltrig/api/platform_bootstrap.py)
`"wire_hitl_resume(kernel, executor=executor, resume_held_write=resume_held_write)"`),
so `pump.requeue` fires only in the Hatchet worker's own kernel, whose notifier
is reached only when that process itself answers a request. A parked
AWAITING_HUMAN work item answered through the API is therefore requeued by no
leg of the bridge.

RISK: `boltrig smoke` and `boltrig check-invariants` are inert in both shipped
images. `_repo_script` looks for `<package parent>/scripts/<name>`
([`boltrig/api/cli.py:27`](../../../boltrig/api/cli.py)
`"path = os.path.join(here, \"scripts\", name)"`) and neither Dockerfile copies
`scripts/` (bounded: `grep -n "^COPY\|^ADD" deploy/*.Dockerfile`, 2026-08-24).
Both commands are advertised in the module docstring and in `--help` without a
note that they only work from a checkout.

RISK: Only two of the four shipped python entrypoints configure logging.
`boltrig/fleet/hatchet_worker.py` and `boltrig/fleet/browser_executor` call
neither `configure_logging()` nor `basicConfig` (bounded:
`grep -rn "configure_logging\|basicConfig" boltrig/ services/ scripts/*.py`,
2026-08-24, pinned tree; the only hits are `asgi.py`, `worker.py` and
`logging_config.py` itself). The gate that enforces the rule checks exactly two
filenames ([`tests/unit/test_logging_is_configured.py:94`](../../../tests/unit/test_logging_is_configured.py)
`"for name in (\"asgi.py\", \"worker.py\"):"`), so the two newer processes
reproduce the handler-less root the module exists to end.

RISK: `boltrig initiate`'s run-once guard is a read-then-write with no
transaction and no uniqueness constraint on "at most one owner-tier user per
tenant", so two concurrent runs with DIFFERENT emails both seat a superadmin.
The module documents this honestly and accepts it
([`boltrig/api/initiate.py:13`](../../../boltrig/api/initiate.py)
`"KNOWN LIMIT - the \"refusing to run twice\" guard is a read-then-write."`).
The sequential refusal IS tested, "which is precisely what makes the race look
covered" (:20).

RISK: `boltrig initiate`, `set-password` and `mint-token` are bound to NO
invariant id. These three are the host-boundary commands, the ones that can act
as somebody else, and the host-boundary attribution rule they exist to satisfy
has tests but no `@pytest.mark.invariant` marker (bounded: `grep -n "invariant"
tests/security/test_operator_seat_ratchet.py tests/security/test_set_password.py`
returns nothing, and `grep -n "initiate\|set-password\|host-boundary"
tests/invariants.yaml` returns no matching entry, 2026-08-24). AGENTS.md
requires exactly this pinning
([`AGENTS.md:53`](../../../AGENTS.md) `"Every security or correctness claim must be pinned to a test with"`).

RISK: The audit-key guard fails OPEN when nothing sets a production signal, and
nothing in the shipped compose sets one. The code says so in its own comment:
[`boltrig/api/boot_guards.py:67`](../../../boltrig/api/boot_guards.py)
`"Nothing sets a production signal by default"`.
A deployment that follows the documented `cp .env.example .env` will warn once
per boot and then run a hash chain keyed by a public constant.

RISK: `bootstrap.build_kernel()` is DEAD. Its docstring claims it is the
"Synchronous entrypoint for uvicorn/worker import-time construction"
([`boltrig/api/bootstrap.py:472`](../../../boltrig/api/bootstrap.py)
`"def build_kernel() -> Kernel:"`), but uvicorn reaches `build_app` and the
worker reaches `build_kernel_async`. Bounded: `rg -n "build_kernel\b" .`
over the pinned tree, 2026-08-24; every hit is either `build_kernel_async` or
`tests/conftest.py::_build_kernel`, a different symbol. A prose claim naming two
callers that do not exist is a live drift hazard.

RISK: `BOLTRIG_EMOTION` is compared with a strict `== "1"`
([`boltrig/api/bootstrap.py:289`](../../../boltrig/api/bootstrap.py)
`"BOLTRIG_EMOTION\", \"\").strip() == \"1\""`), while every other flag in this
file goes through `is_truthy`. `BOLTRIG_EMOTION=true` silently registers nothing
on the manifest path.

RISK: A wrong `BOLTRIG_MANIFEST` path is silently ignored rather than refused.
`_find` returns the first path that EXISTS and the env value is simply the first
candidate ([`boltrig/api/bootstrap.py:67`](../../../boltrig/api/bootstrap.py)
`"def _find(paths) -> str | None:"`), so a typo boots the repository's
`manifest.example.yaml` and logs it as a normal manifest boot.

RISK: `boltrig audit-verify --tenant` defaults to `BOLTRIG_TENANT_ID` or
`default` ([`boltrig/api/audit_verify.py:103`](../../../boltrig/api/audit_verify.py)
`"default=os.environ.get(\"BOLTRIG_TENANT_ID\", \"default\")"`), which is not
necessarily the manifest's tenant. Verifying the wrong tenant's empty chain
exits 0, and nothing in the command compares the tenant against the manifest.

RISK: `docs/decisions/0018-held-write-resume.md` is stale on a load-bearing
fact. Its reserved section asserts nothing serves the Hatchet tasks
([`docs/decisions/0018-held-write-resume.md:325`](../../../docs/decisions/0018-held-write-resume.md)
`"stack serves the Hatchet tasks"`), which the
`hatchet-worker` compose service now contradicts. A reader who trusts the
decision would conclude the durable lane is dead when it is served.

## 12. OPEN QUESTIONS

1. Does the `hatchet-worker` service actually reach `ctx.aio_wait_for` and
   consume the approval event the API pushes? Decision 0018 reserved that path
   as untested ([`docs/decisions/0018-held-write-resume.md:333`](../../../docs/decisions/0018-held-write-resume.md)
   `"UNTESTED CODE PATH, RESERVED"`). Settled by a live Hatchet run that pauses,
   is approved through the API, and reaches CONSUMED with the engine wait as the
   only trigger.

2. Is the memory-projection fanout executor registered anywhere other than the
   API process? `wire_memory_projection_executor` is called only from
   `_build_platform_services` ([`boltrig/api/platform_bootstrap.py:105`](../../../boltrig/api/platform_bootstrap.py)
   `"wire_memory_projection_executor(kernel, tenant, executor)"`) and the fleet
   worker never calls it. Settled by tracing which process actually delivers a
   queued memory projection in a Hatchet-live deployment.

3. Does the API process's birth receipt describe the manifest the kernel was
   SEEDED with? The kernel is seeded from the raw snapshot
   ([`boltrig/api/bootstrap.py:452`](../../../boltrig/api/bootstrap.py)
   `"await _seed_from_manifest(kernel, manifest, model_catalogue=model_catalogue)"`)
   while the receipt digests the desired-state OVERLAY
   ([`boltrig/api/app_composition.py:39`](../../../boltrig/api/app_composition.py)
   `"manifest=effective_manifest,"`). All three processes are consistent with each
   other, so no drift is visible between them; whether `manifest_generation` is
   meant to describe the applied or the desired manifest is not stated anywhere I
   read. Settled by the birth-profile projection's own contract in
   `boltrig/config/birth_profile_projection.py` and the SEC-WRK-27 acceptance.

4. Does `boltrig worker`'s always-zero exit
   ([`boltrig/api/cli.py:266`](../../../boltrig/api/cli.py) `"worker_main()"`
   followed by `return 0`) matter to any supervisor? Compose runs
   `python -m boltrig.api.worker` directly rather than through the CLI, so the
   CLI path may be operator-only. Settled by checking whether any deployment unit
   outside this repo uses `boltrig worker`.

5. Is `boltrig/api/` deliberately outside the architecture gate, or an omission?
   The gate's comment explains the kernel deny-list but says nothing about the
   composition root ([`scripts/check_architecture.py:54`](../../../scripts/check_architecture.py)
   `"The kernel composes every sibling package"`).
   Settled by the gate's owner stating whether `boltrig.api` is intended to be
   unconstrained.

6. Does `hitl.set_resume_notifier` overwrite or compose? The kernel stores a
   single callable ([`boltrig/kernel/hitl.py:94`](../../../boltrig/kernel/hitl.py)
   `"self._resume_notifier = notifier"`), so a second `wire_hitl_resume` in one
   process REPLACES the first. In production no process calls it twice, but a
   test or an embedder that does would silently lose legs. Settled by deciding
   whether the seam should refuse a second registration.

## 13. Requirements

Status vocabulary is the contract's. `invariant` is the `tests/invariants.yaml`
id that binds the row, or `-` when the row is unbound. Every unbound security or
correctness row is also recorded in RISKS above.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1300 | Each serving process composes exactly one manifest snapshot, one trusted Codex configuration and one Bifrost model catalogue, through compose_process_model_runtime. | IMPLEMENTED | boltrig/api/model_runtime_composition.py:31 "return manifest_path, manifest, codex_config, BifrostModelCatalogue()" | CODEX-COMPOSITION-1 |
| BT-REQ-1301 | The manifest's non-secret runtime environment is exported before the Codex configuration and the catalogue are built, and that export fills only variables the process environment leaves absent. | IMPLEMENTED | tests/unit/test_model_runtime_composition.py::test_manifest_gateway_is_exported_before_process_model_resources_are_composed | CODEX-COMPOSITION-1 |
| BT-REQ-1302 | compose_api_app injects the identical codex_config object into the kernel factory, the chat wiring, the platform factory and the app spawner. | IMPLEMENTED | tests/unit/test_codex_trusted_composition.py::test_api_composition_shares_one_codex_config_with_every_factory | CODEX-COMPOSITION-1 |
| BT-REQ-1303 | build_kernel_async never re-reads the manifest when the caller injects a snapshot. | IMPLEMENTED | tests/unit/test_codex_trusted_composition.py::test_kernel_uses_the_composition_manifest_snapshot_without_rereading | CODEX-COMPOSITION-1 |
| BT-REQ-1304 | build_kernel_async refuses to boot when an injected sensitive endpoint id disagrees with the snapshot's configured sensitive endpoint. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:440 "sensitive model routing changed during process composition"; no test found (bounded: grep -rn "sensitive model routing changed" . --include='*.py') | - |
| BT-REQ-1305 | The audit-key boot guard runs as the first statement of build_kernel_async, before any store connection. | IMPLEMENTED | boltrig/api/bootstrap.py:419 "refuse_default_audit_key_in_prod()"; guard proven by tests/security/test_audit_key_provisioning.py::test_every_shipped_placeholder_is_fatal_under_a_production_signal | K-19 |
| BT-REQ-1306 | build_store returns a durable PostgresStore when DATABASE_URL is set and an in-memory store otherwise. | IMPLEMENTED | boltrig/api/bootstrap.py:89 "if settings.database_url:"; tests/unit/test_bootstrap_store.py::test_runtime_store_never_replays_mutable_bootstrap | - |
| BT-REQ-1307 | No runtime boot applies schema.sql: every PostgresStore connection this area opens passes apply_schema=False, with or without RLS. | IMPLEMENTED | boltrig/api/bootstrap.py:100 "apply_schema=False, rls=rls"; tests/unit/test_bootstrap_store.py::test_runtime_store_never_replays_mutable_bootstrap | - |
| BT-REQ-1308 | The shared rate-limit counter and the event relay are both constructed from REDIS_URL, and the relay is told whether a production signal is present. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:423 "counter = build_counter(os.environ.get(\"REDIS_URL\"))"; no test asserts this wiring at the composition root (bounded: grep -rn "build_counter\\|build_event_relay" tests/) | - |
| BT-REQ-1309 | A manifest boot constructs the Kernel with the manifest's blocking-verb set, its HITL approval timeout and its development posture. | IMPLEMENTED | boltrig/api/bootstrap.py:446 "blocking_verbs=manifest.blocking_verbs(),"; tests/unit/test_codex_trusted_composition.py::test_kernel_uses_the_composition_manifest_snapshot_without_rereading | CODEX-COMPOSITION-1 |
| BT-REQ-1310 | A boot that finds no manifest seeds a minimal offline demo tenant named 'default' rather than failing. | IMPLEMENTED | boltrig/api/bootstrap.py:459 "no manifest found; booted minimal demo tenant"; tests/integration/test_manifest_boot.py::test_healthz_green | - |
| BT-REQ-1311 | The manifest seed registers web.fetch before rehydrating store-persisted adapters, so the web row is never warned about and then registered. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:301 "a pure ordering artifact that read"; no test asserts the order (bounded: grep -rn "_register_web_fetch\\|_rehydrate_store_adapters" tests/) | - |
| BT-REQ-1312 | Adapter rehydration skips ids the manifest already registered this boot and emits a shape-specific warning for every row it cannot reconstruct. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:239 "the manifest registered this id this boot already"; no test drives _rehydrate_store_adapters (bounded: grep -rn "_rehydrate_store_adapters" tests/) | SEC-22 |
| BT-REQ-1313 | Skill-directory loading is best-effort: a bad skill file warns and the boot continues. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:312 "a bad skill file should not stop boot"; no test seeds a bad skill file at boot (bounded: grep -rn "load_skills_dir" tests/) | - |
| BT-REQ-1314 | The pending desktop-command registry is created, and the desktop.* verbs registered, only when BOLTRIG_DESKTOP_HANDS is truthy. | IMPLEMENTED | boltrig/api/bootstrap.py:135 "Default OFF: a kernel that does"; tests/security/test_desktop_hands.py | - |
| BT-REQ-1315 | External MCP servers declared in the manifest are registered inert, pending the review gate, and their bearers bind by credential reference rather than raw material. | IMPLEMENTED | boltrig/api/bootstrap.py:206 "each INERT pending review (SEC-22)"; tests/integration/test_round_fifteen_bundle.py | SEC-22 |
| BT-REQ-1316 | The agent invoker is set last in kernel construction and carries the same provider, catalogue and sensitive role as every spawner the process owns. | IMPLEMENTED | boltrig/api/bootstrap.py:461 "kernel.set_agent_invoker("; tests/unit/test_codex_trusted_composition.py::test_make_agent_invoker_threads_runtime_policy_to_resolver | CODEX-COMPOSITION-1 |
| BT-REQ-1317 | asgi.py configures root logging before importing anything else from boltrig. | IMPLEMENTED | boltrig/api/asgi.py:18 "configure_logging()"; tests/unit/test_logging_is_configured.py::test_both_entrypoints_configure_logging_and_neither_rolls_its_own | - |
| BT-REQ-1318 | Both the ASGI entrypoint and the fleet worker resolve the configured add-on set at import, so an unregistered name is a startup failure rather than a mid-turn one. | IMPLEMENTED-UNTESTED | boltrig/api/asgi.py:26 "_ADDONS = active_addons()" and boltrig/api/worker.py:58 "_ADDONS = active_addons()"; no test imports either module with a bad BOLTRIG_ADDONS (bounded: grep -rn "BOLTRIG_ADDONS" tests/) | - |
| BT-REQ-1319 | The FastAPI object is built at import while the kernel, spawner, chat service and platform bag are built inside the ASGI lifespan on the serving loop. | IMPLEMENTED | boltrig/kernel/app.py:276 "if not hasattr(app.state, \"kernel\"):"; tests/integration/test_manifest_boot.py::test_invoke_through_booted_stack | - |
| BT-REQ-1320 | The API kernel factory publishes an 'api' birth receipt only when the desired-state overlay of the snapshot is available, and publishes nothing when it is not. | IMPLEMENTED | boltrig/api/app_composition.py:34 "if manifest is not None and effective_manifest is None:"; tests/unit/test_codex_trusted_composition.py::test_api_composition_shares_one_codex_config_with_every_factory | CODEX-COMPOSITION-1 |
| BT-REQ-1321 | select_principal_resolver refuses to boot on a partial manifest OIDC trio and on a manifest trio that differs from a simultaneously configured process trio. | IMPLEMENTED | tests/security/test_identity_manifest_wiring.py::test_manifest_oidc_partial_or_process_drift_refuses_boot | - |
| BT-REQ-1322 | With no authentication configured, the selected resolver refuses every request with 401 rather than falling through to a permissive default. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:496 "authentication is not configured"; no test drives the deny-all branch (bounded: grep -rn "deny_all\\|authentication is not configured" tests/) | - |
| BT-REQ-1323 | make_platform_factory binds every immutable boot input by partial application and leaves only the kernel to be supplied at lifespan. | IMPLEMENTED | boltrig/api/platform_bootstrap.py:158 "return functools.partial("; tests/unit/test_readiness.py::test_platform_composition_threads_the_manifest_into_readiness | CODEX-COMPOSITION-1 |
| BT-REQ-1324 | The platform factory registers the durable workers and the Boltrig task definitions, and a registration fault warns without failing the boot. | IMPLEMENTED-UNTESTED | boltrig/api/platform_bootstrap.py:106 "boltrig task registration failed"; no test drives the failing branch (bounded: grep -rn "register_boltrig_tasks" tests/) | - |
| BT-REQ-1325 | The platform projection carries composition truth only: a configured boolean and the non-secret model id, never provider topology, URLs or upstream keys. | IMPLEMENTED | boltrig/api/platform_bootstrap.py:37 "Projection receives composition truth only, never provider details."; tests/unit/test_codex_trusted_composition.py::test_api_composition_shares_one_codex_config_with_every_factory | CODEX-COMPOSITION-1 |
| BT-REQ-1326 | ReadinessService is constructed with the process manifest snapshot, the selected executor, the stack-tool status provider and the password-reset delivery pair. | IMPLEMENTED | tests/unit/test_readiness.py::test_platform_composition_threads_the_manifest_into_readiness | CODEX-COMPOSITION-1 |
| BT-REQ-1327 | worker.py configures logging and resolves add-ons at module import, using the same declared configuration as the ASGI entrypoint and rolling none of its own. | IMPLEMENTED | tests/unit/test_logging_is_configured.py::test_both_entrypoints_configure_logging_and_neither_rolls_its_own | - |
| BT-REQ-1328 | The fleet worker composes the same one-snapshot runtime as the API and builds its kernel through build_kernel_async on the running loop. | IMPLEMENTED | tests/unit/test_codex_trusted_composition.py::test_standalone_worker_shares_one_codex_provider_with_its_spawner | CODEX-COMPOSITION-1 |
| BT-REQ-1329 | A failed desired-fleet overlay degrades the worker to the minimal default org and never crashes the boot. | IMPLEMENTED-UNTESTED | boltrig/api/worker.py:285 "manifest load failed (%s); using the default org"; the failing branch has no test (bounded: grep -rn "effective_manifest_from_desired" tests/) | - |
| BT-REQ-1330 | The worker records a permanent-fleet startup observation only when the desired overlay actually applied. | IMPLEMENTED | tests/fleet/test_worker_janitors.py::test_default_org_does_not_claim_permanent_fleet_startup_parity | SEC-WRK-27 |
| BT-REQ-1331 | The worker publishes a 'fleet' birth receipt over the overlaid manifest, its own add-on snapshot and the process Codex configuration. | IMPLEMENTED | tests/unit/test_codex_trusted_composition.py::test_standalone_worker_shares_one_codex_provider_with_its_spawner | CODEX-COMPOSITION-1 |
| BT-REQ-1332 | The fleet worker starts seven named background loops: audit-anchor, hitl-expiry, audit-outbox, fleet stack-tool heartbeat, retention, workflow-scheduler and session-distillation. | IMPLEMENTED | boltrig/api/worker.py:341 "return ("; tests/fleet/test_worker_janitors.py::test_the_fleet_worker_starts_the_retention_janitor | SEC-74 |
| BT-REQ-1333 | Every janitor is disabled only by an explicit interval of zero or less, and the worker logs which choice it made so 'off' is a decision on the record. | IMPLEMENTED | boltrig/api/worker.py:176 "'off' is a decision on the record rather than the silence it used to be."; tests/fleet/test_worker_janitors.py::test_the_retention_janitor_is_off_only_when_someone_turns_it_off | SEC-74 |
| BT-REQ-1334 | The fleet stack-tool heartbeat starts only when REDIS_URL is configured, and the worker logs which case applied. | IMPLEMENTED-UNTESTED | boltrig/api/worker.py:324 "fleet stack-tool heartbeat not started (REDIS_URL not configured)"; the enabled branch has no test (bounded: grep -rn "run_fleet_tool_heartbeat" tests/) | - |
| BT-REQ-1335 | When the delegation pump loop ends, every started background task is cancelled and gathered and the kernel is closed. | IMPLEMENTED | boltrig/api/worker.py:431 "await _stop_background_tasks(tasks)"; tests/unit/test_codex_trusted_composition.py::test_standalone_worker_shares_one_codex_provider_with_its_spawner asserts kernel.aclose was awaited once | - |
| BT-REQ-1336 | The fleet worker installs its own executor-only HITL resume notifier so the expiry sweep's reconciliation pass has a notifier to re-fire. | IMPLEMENTED-UNTESTED | boltrig/api/worker.py:340 "wire_hitl_resume(kernel, executor=executor)"; no test exercises the worker-side notifier (bounded: grep -rn "wire_hitl_resume" tests/) | NFR-REL-03 |
| BT-REQ-1337 | A KeyboardInterrupt stops the fleet worker cleanly with a log line rather than a traceback. | IMPLEMENTED-UNTESTED | boltrig/api/worker.py:440 "except KeyboardInterrupt:"; no test (bounded: grep -rn "KeyboardInterrupt" tests/) | - |
| BT-REQ-1338 | The distribution installs exactly one console script, boltrig, pointing at boltrig.api.cli:main. | IMPLEMENTED | pyproject.toml:126 "boltrig = \"boltrig.api.cli:main\""; the kernel image smoke-tests it at deploy/kernel.Dockerfile:184 "/usr/local/bin/boltrig --help >/dev/null" | - |
| BT-REQ-1339 | The CLI declares thirteen subcommands, requires one to be given, and dispatches every declared name to a real module. | IMPLEMENTED | boltrig/api/cli.py:33 "sub = parser.add_subparsers(dest=\"cmd\", required=True)"; tests/security/test_worker_feature_ledger.py::test_every_native_command_is_classified_and_registered | WRK-06 |
| BT-REQ-1340 | boltrig serve binds 127.0.0.1 unless an explicit --host is given. | IMPLEMENTED | tests/unit/test_cli.py::test_serve_is_loopback_only_unless_host_is_explicit | SEC-135 |
| BT-REQ-1341 | The three identity subcommands resolve their tenant identically: the flag, else the session tenant, else 'default'. | IMPLEMENTED-UNTESTED | boltrig/api/cli.py:215 "tenant = args.tenant or load_settings().session_tenant or \"default\""; no test drives _dispatch_identity (bounded: grep -rn "_dispatch_identity" tests/) | - |
| BT-REQ-1342 | boltrig smoke and boltrig check-invariants resolve a script from the source tree and exit 2 when it is absent, which is the case inside both shipped images because neither Dockerfile copies scripts/. | IMPLEMENTED-UNTESTED | boltrig/api/cli.py:274 "script for '{args.cmd}' not found"; bounded: grep -n "^COPY\\|^ADD" deploy/kernel.Dockerfile deploy/fleet.Dockerfile, 2026-08-24, copies only kernel-entrypoint.py and fleet-entrypoint.sh | - |
| BT-REQ-1343 | boltrig doctor merges an optional dotenv over a copy of the process environment before running the static checks. | IMPLEMENTED-UNTESTED | boltrig/api/cli.py:287 "env = load_env_file(args.env_file, base=env)"; the merge is not driven from the CLI in any test (bounded: grep -rn "load_env_file" tests/) | - |
| BT-REQ-1344 | The CLI subcommand set is closed against the non-HTTP feature ledger, so a new subcommand cannot ship without a discover/configure/operate/observe/recover classification. | IMPLEMENTED | tests/security/test_worker_feature_ledger.py::test_every_native_command_is_classified_and_registered | WRK-06 |
| BT-REQ-1345 | boltrig chat is a thin client: head mode streams POST /v1/chat over SSE with a bearer PAT and embeds no agent runtime. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_stream_turn_yields_events_and_sends_bearer_auth | - |
| BT-REQ-1346 | The chat token resolves flag, then BOLTRIG_CLI_TOKEN, then the config file, and never appears in an error message. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_resolve_setting_order_flag_beats_env_beats_config and ::test_stream_turn_401_is_a_clean_error_that_never_carries_the_token | - |
| BT-REQ-1347 | A malformed CLI config file is a clean error, never a silent fall-through to 'no token configured'. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_load_config_malformed_toml_is_a_clean_error | - |
| BT-REQ-1348 | The terminal SSE parser drops comments and malformed or non-object payloads without failing the turn. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_parse_sse_drops_malformed_and_non_dict_payloads | - |
| BT-REQ-1349 | A 202 accepted-steer response becomes a terminal queued event and any other non-200 becomes a one-line clean error. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_stream_turn_202_queued_is_an_accepted_terminal_event and ::test_stream_turn_other_202_remains_a_clean_error | - |
| BT-REQ-1350 | Gateway mode validates a target slug against the kernel's own slug rule and drops malformed inbound frames. | IMPLEMENTED | tests/unit/test_chat_cli.py::test_clean_target_matches_the_kernel_slug_rule and ::test_decode_frame_drops_malformed_lines | - |
| BT-REQ-1351 | boltrig initiate seats exactly one founding OWNER and refuses to run again once any owner-tier user exists in the tenant, touching nothing on refusal. | IMPLEMENTED | tests/security/test_first_party_login.py::test_initiate_is_idempotent_and_refuses_twice | - |
| BT-REQ-1352 | The seeded founding owner is flagged must_change_password so the provisioning credential cannot remain the live production gate. | IMPLEMENTED-UNTESTED | boltrig/api/initiate.py:110 "must_change_password=True,"; the idempotency test asserts role and onboarding but not this flag (tests/security/test_first_party_login.py:377) | - |
| BT-REQ-1353 | Both host-boundary password commands bind the current tenant before any RLS-scoped read or write. | IMPLEMENTED-UNTESTED | boltrig/api/initiate.py:89 "bind before any RLS-scoped read/write"; no test asserts the ordering (bounded: grep -rn "set_current_tenant" tests/security/test_set_password.py tests/security/test_first_party_login.py) | - |
| BT-REQ-1354 | The initiate audit row carries the email, role, org and workspace and never the password. | IMPLEMENTED-UNTESTED | boltrig/api/initiate.py:146 "Audit the owner seed keys-only (D8): the email, never the password."; tests/security/test_auth_audit_is_keys_only.py covers login, not auth.initiate | - |
| BT-REQ-1355 | The initiate run-once guard is a read-then-write with no transaction and no uniqueness constraint, so two concurrent runs with different emails both seat a superadmin. | IMPLEMENTED | boltrig/api/initiate.py:13 "KNOWN LIMIT - the 'refusing to run twice' guard is a read-then-write."; the sequential refusal alone is tested by tests/security/test_first_party_login.py::test_initiate_is_idempotent_and_refuses_twice | - |
| BT-REQ-1356 | boltrig set-password refuses a user that does not exist and never creates an identity or a grant. | IMPLEMENTED | tests/security/test_set_password.py::test_set_password_refuses_an_unknown_user | - |
| BT-REQ-1357 | A successful set-password clears must_change_password, so rotating the credential discharges the forced-rotation clamp. | IMPLEMENTED-UNTESTED | boltrig/api/initiate.py:220 "Rotating the credential IS the rotation D7 requires"; tests/security/test_set_password.py does not assert the flag | - |
| BT-REQ-1358 | The set-password audit row attributes the act to the host boundary with the subject in on_behalf_of, and a matching security-stream event is written best-effort. | IMPLEMENTED | boltrig/api/initiate.py:224 "D6: the actor is the HOST BOUNDARY, never the target user."; tests/security/test_operator_seat_ratchet.py | - |
| BT-REQ-1359 | Both password commands resolve the secret as the flag, then BOLTRIG_INIT_PASSWORD, then a confirmed interactive prompt, and exit 2 on a mismatch. | IMPLEMENTED-UNTESTED | boltrig/api/initiate.py:175 and :254 "secret = password or os.environ.get(\"BOLTRIG_INIT_PASSWORD\")"; no test drives the prompt path | - |
| BT-REQ-1360 | wire_hitl_resume installs exactly one resume notifier on the kernel HITL manager, and the kernel never imports the fleet to do it. | IMPLEMENTED | boltrig/api/bootstrap.py:354 "kernel.hitl.set_resume_notifier(_on_answer)"; tests/security/test_held_write_resume.py::test_answering_the_approval_carries_out_the_held_write | NFR-REL-03 |
| BT-REQ-1361 | The resume notifier runs four independent legs in a fixed order and each fails safe, so a leg fault never voids the recorded answer. | IMPLEMENTED | boltrig/api/bootstrap.py:345 "resume is best-effort; the answer stands (P9)"; tests/security/test_held_write_resume.py::test_answering_the_approval_carries_out_the_held_write | NFR-REL-03 |
| BT-REQ-1362 | The held-write leg does nothing for a non-APPROVAL request, a request with no run id, or an absent resume callable. | IMPLEMENTED-UNTESTED | boltrig/api/hitl_resume_bridge.py:17 "if resume is None or request.type != HITLType.APPROVAL or not request.run_id:"; no test drives the three guards individually | - |
| BT-REQ-1363 | The held-write leg defers to origin finalization when replaying the write would discard a one-time webhook secret. | IMPLEMENTED | boltrig/api/hitl_resume_bridge.py:20 "if await approval_requires_origin_finalization(kernel.store, request):"; tests/security/test_workflow_triggers.py | - |
| BT-REQ-1364 | A request that another lane also paused on is not replayed by the held-write leg, so the interpreter and held-write lanes never race the approval CAS. | IMPLEMENTED | boltrig/kernel/held_call.py:250 "Mutually exclusive with the durable/interpreter route by the reserved prefix"; tests/security/test_held_write_resume.py::test_delivering_the_resume_twice_executes_the_write_once | SEC-14 |
| BT-REQ-1365 | Delivering the resume twice, from the notifier and from either run id, executes the held write exactly once and leaves exactly one consumed approval and one tool-call row. | IMPLEMENTED | tests/security/test_held_write_resume.py::test_delivering_the_resume_twice_executes_the_write_once | NFR-REL-03 |
| BT-REQ-1366 | A missing or unreadable held-call seal refuses the resume and never reconstructs the call from anything else. | IMPLEMENTED | tests/security/test_held_write_resume.py::test_a_missing_seal_refuses_and_never_guesses_the_call and ::test_only_the_sealed_params_can_execute_the_held_write | SEC-14 |
| BT-REQ-1367 | The API process wires the executor and held-write legs of the answer bridge and does not wire the pump leg. | IMPLEMENTED | boltrig/api/platform_bootstrap.py:108 "wire_hitl_resume(kernel, executor=executor, resume_held_write=resume_held_write)"; bounded: grep -rn "wire_hitl_resume" boltrig/ gives exactly three production call sites | - |
| BT-REQ-1368 | The chat factory and the held-write resume callable share one ChatService instance through a late-bound holder, so factory ordering in the lifespan does not matter. | IMPLEMENTED | boltrig/api/bootstrap.py:578 "holder = {}" with :616 "holder[\"service\"] = service" and :620 "service = holder.get(\"service\")"; tests/security/test_held_write_resume.py::test_the_continuation_reaches_the_stream_and_the_transcript | SEC-14 |
| BT-REQ-1369 | The API chat factory re-reads the manifest from disk at lifespan time and silently falls back to the default ChatConfig when that read fails. | IMPLEMENTED | boltrig/api/bootstrap.py:590 "chat_cfg = load_manifest(manifest_path).chat" with the bare handler at :591 "except Exception:" | - |
| BT-REQ-1370 | A HITL approval verdict is harvested as a governed endorsement or block reuse signal, best-effort, and a harvest fault never voids the answer. | IMPLEMENTED-UNTESTED | boltrig/api/bootstrap.py:358 "Turn a HITL verdict into a reuse signal"; no test drives _harvest_hitl_signal (bounded: grep -rn "harvest_reuse_signal" tests/) | - |
| BT-REQ-1371 | boltrig audit-verify exits 0 when the chain re-derives, 1 when it does not, and 2 when it could not look, and 2 is never reported as success. | IMPLEMENTED | tests/unit/test_audit_verify_cli.py::test_cannot_look_is_exit_2_and_never_0 | K-19 |
| BT-REQ-1372 | Segment verification seeds the walk from the row before the window and prints the range it did not check. | IMPLEMENTED | tests/unit/test_audit_verify_cli.py::test_a_segment_verifies_only_when_seeded_from_the_preceding_row | - |
| BT-REQ-1373 | Segment verification still names tampering that occurs above the cut. | IMPLEMENTED | tests/unit/test_audit_verify_cli.py::test_a_segment_still_catches_tampering_inside_it | - |
| BT-REQ-1374 | The verifier names the number and boundaries of retired key epochs on every outcome, and its failure text names both possible causes. | IMPLEMENTED-UNTESTED | boltrig/api/audit_verify.py:73 "retired key epoch(s), boundaries" and :83 "Either the chain was altered, or a key was"; no test asserts the message shape | - |
| BT-REQ-1375 | No scheduled or automated invocation of boltrig audit-verify exists anywhere in the repository, so the tamper-evidence chain is re-derived only when an operator remembers. | DEAD | bounded: grep -rn "audit-verify" . excluding docs/brownfield-spec, 2026-08-24, pinned tree; hits are only boltrig/api/audit_verify.py, boltrig/api/cli.py:53 and :249, docs/claim-inventory.tsv:315, tests/worker_feature_ledger.py:845 and tests/unit/test_audit_verify_cli.py | - |
| BT-REQ-1376 | register_agent_support registers the skill shelf, the work-read adapter, peer messaging and chat presentation, and it runs on both the demo and the manifest seed paths. | IMPLEMENTED | boltrig/api/agent_tool_bootstrap.py:21 "build_skill_shelf_adapter(kernel.store)"; tests/adapters/test_work_read_adapter.py | - |
| BT-REQ-1377 | A tenant with no named agents is seeded a 'general' script agent marked as the intake default. | IMPLEMENTED-UNTESTED | boltrig/api/agent_tool_bootstrap.py:27 "if not await kernel.store.list_named_agents(tenant_id):"; no test asserts the seed (bounded: grep -rn "default_for_intake" tests/) | - |
| BT-REQ-1378 | Progressive disclosure of SKILLS is the shelf's search verb, which returns descriptions only and never the prompt fragment body. | IMPLEMENTED | boltrig/skills/shelf.py:13 "NEVER the prompt_fragment body. This is the progressive-"; tests/security/test_round_fifteen.py::test_skill_search_returns_descriptions_not_bodies | FR-SKILL-01 |
| BT-REQ-1379 | Progressive disclosure of TOOLS is computed inside the kernel and is no part of the composition root, which registers adapters and never ranks or budgets an offer. | IMPLEMENTED | boltrig/kernel/mcp_tools_list.py:49 "page = tool_disclosure.offer_page(candidates, rt.grants, rt.skills, cursor)"; tests/unit/test_tool_disclosure.py | - |
| BT-REQ-1380 | Device action verbs are registered only when this process holds a lease signing key, and are absent otherwise. | IMPLEMENTED | tests/security/test_device_dispatch_adapter.py::test_boot_registration_is_key_gated_and_uses_canonical_registry | SEC-WRK-07 |
| BT-REQ-1381 | Camera lease verbs follow the same key gate as device verbs and are absent when no signer is available. | IMPLEMENTED-UNTESTED | boltrig/api/camera_bootstrap.py:17 "camera lease verbs disabled (lease signing key unavailable)"; bounded: grep -rn "register_camera_actions\\|camera_bootstrap" tests/ returns nothing, 2026-08-24 | - |
| BT-REQ-1382 | Every serving process publishes one bounded birth receipt whose fields are opaque digests, and a write failure warns and returns False without failing the boot. | IMPLEMENTED | boltrig/api/birth_profile_startup.py:38 "except Exception:" with :40 "birth-profile startup receipt unavailable (process=%s)"; tests/security/test_birth_profile_receipts.py::test_receipt_contract_rejects_unbounded_or_incoherent_evidence | - |
| BT-REQ-1383 | Exactly three process kinds may publish a birth receipt, api, fleet and hatchet, and the database enforces that set. | IMPLEMENTED | boltrig/store/schema.sql:807 "CHECK (process_kind IN ('api','fleet','hatchet'))"; tests/store/test_birth_profile_store_parity.py::test_all_boot_instance_receipts_are_tenant_scoped_on_both_stores | - |
| BT-REQ-1384 | One declared logging configuration installs a root handler whose formatter carries a timestamp, a level name and a logger name. | IMPLEMENTED | tests/unit/test_logging_is_configured.py::test_root_gets_a_real_handler_so_nothing_routes_through_lastresort and ::test_info_actually_reaches_a_handler_and_is_formatted | - |
| BT-REQ-1385 | An unreadable BOLTRIG_LOG_LEVEL falls back to INFO rather than silencing the process. | IMPLEMENTED | tests/unit/test_logging_is_configured.py::test_an_unreadable_level_falls_back_rather_than_silencing_the_process | - |
| BT-REQ-1386 | Only two of the four shipped python entrypoints configure logging; boltrig.fleet.hatchet_worker and boltrig.fleet.browser_executor configure none, and the gate that enforces the rule checks only asgi.py and worker.py. | IMPLEMENTED | tests/unit/test_logging_is_configured.py:94 "for name in ('asgi.py', 'worker.py'):"; bounded: grep -rn "configure_logging\|basicConfig" boltrig/ services/ scripts/*.py, 2026-08-24, pinned tree | - |
| BT-REQ-1387 | bootstrap.build_kernel, the synchronous wrapper, is unreachable from every shipped entrypoint despite a docstring naming uvicorn and the worker as its callers. | DEAD | boltrig/api/bootstrap.py:472 "Synchronous entrypoint for uvicorn/worker import-time construction."; bounded: rg -n "build_kernel\b" over the pinned tree, 2026-08-24, every hit is build_kernel_async or tests/conftest.py::_build_kernel | - |

Counts: DEAD 2, IMPLEMENTED 61, IMPLEMENTED-UNTESTED 25, total 88.
