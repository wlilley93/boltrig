---
area: "11 Configuration: the manifest, the environment, and release mode"
id-block: BT-REQ-1100 to BT-REQ-1199
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48
author-agent: spec-author-11
date: 2026-08-24
---

# SPEC-11 Configuration: the manifest, the environment, and release mode

## Bound of this reading

Read exhaustively, line by line: `boltrig/config/manifest.py` (888 lines),
`boltrig/config/manifest_agents.py`, `boltrig/config/manifest_apply.py`,
`boltrig/config/manifest_reconcile.py`, `boltrig/config/manifest_runtime.py`,
`boltrig/config/settings.py`, `boltrig/config/environment.py`,
`boltrig/config/weak_secrets.py`, `boltrig/config/admin.py`,
`boltrig/config/spawn_rules.py`, `boltrig/config/spawn_rule_revisions.py`,
`boltrig/config/dev_posture.py`, `boltrig/config/dev_egress.py`,
`boltrig/config/birth_profile.py`, `boltrig/config/birth_profile_projection.py`,
`boltrig/release_mode.py`, `boltrig/branding.py`, `boltrig/api/config_validate.py`,
`manifest.example.yaml` (577 lines), `.env.example` (418 lines),
`deploy/compose.release.yml`, `scripts/validate_release_compose.py`,
`scripts/validate_public_product.py`, and the composition roots that hold a
manifest snapshot (`boltrig/api/bootstrap.py`, `boltrig/api/app_composition.py`,
`boltrig/api/model_runtime_composition.py`, `boltrig/api/platform_bootstrap.py`,
`boltrig/api/auth_selection.py`, `boltrig/api/worker.py`,
`boltrig/fleet/hatchet_bootstrap.py`, `boltrig/fleet/hatchet_app.py`).

Sampled, not exhaustive: the thirty-five `boltrig/config/control_*.py` modules
(the governed control-plane surface). They live in the `boltrig/config/` package
but are the control-plane subsystem, not the configuration-loading subsystem.
Every one had its top-level definitions listed and its module docstring read;
depth was taken only where a control verb writes a `ConfigRevision` or reads a
manifest section (`control_plane.py`, `control_mcp.py`, `control_budget.py`,
`permanent_fleet.py`). Treat this file as authoritative for the loader, the
snapshot, the environment and release mode, and as an index only for the
`control_*` surface.

Not read: any deployed stack, any other worktree, `manifest.yaml` (gitignored,
absent from the pinned tree).

`manifest.yaml` does not exist in the referent. `.gitignore:5` `"manifest.yaml"`
excludes it, so every statement below about "the manifest" is a statement about
the loader plus the shipped template `manifest.example.yaml`.

---

## 2. Purpose

This subsystem answers "what is this deployment, and what is this tenant" from
two files that are not code. `.env` supplies PROCESS wiring (where the database
is, which secret store, the egress proxy, which auth door) and is read once into
a frozen `Settings`; `manifest.yaml` supplies per-tenant POLICY (who the org is,
which models, which agents, which spawn rules, which HITL verbs block) and is
parsed into frozen dataclasses that seed the store. The split is what lets one
image serve many tenants
([`boltrig/config/settings.py:5`](../../../boltrig/config/settings.py) `"These are kept apart so the same image runs many tenants"`).

## 3. Boundaries

**Owns.** YAML parsing and `${ENV}` interpolation; the typed manifest
dataclasses and their validation; the environment-to-`Settings` projection; the
production and development environment classification; the placeholder-secret
predicate; the release-mode vocabulary; the product-name derivation; the
`config-validate` preflight; and the store projection of a manifest
(`apply_manifest`).

**Must not touch.** The loader has no I/O beyond `open()` and no store access.
`apply_manifest` is the only part of this area that writes, and it writes only
through the `Store` protocol and `kernel.register_adapter`
([`boltrig/config/manifest_apply.py:21`](../../../boltrig/config/manifest_apply.py) `"async def _seed_call(store: Any, method: str"`).

**Forbidden imports.** `boltrig/config/environment.py` is deliberately
dependency-free and import-safe so a guard can classify the environment before
anything else is constructed
([`boltrig/config/environment.py:1`](../../../boltrig/config/environment.py) `"Shared, import-safe deployment-environment classification"`).
`boltrig/release_mode.py` is pure stdlib on purpose so a bare CI runner can
import it with nothing installed
([`scripts/validate_release_compose.py:15`](../../../scripts/validate_release_compose.py) `"boltrig.release_mode is pure stdlib and ships in the tree"`).
Adapters are a foundation layer and may not import upward into config, which is
why the egress-diversion value type lives in `boltrig.models` and is only
re-exported from config
([`boltrig/config/dev_egress.py:70`](../../../boltrig/config/dev_egress.py) `"adapters are a FOUNDATION layer that may not depend upward on config"`).

**Shared with other areas.** `boltrig/config/control_*.py` (control plane),
`boltrig/config/permanent_fleet.py` (durable fleet desired state),
`boltrig/config/integration_catalogue.py` (integrations),
`boltrig/config/channel_addressing.py` (channels). This spec describes only
their interaction with the manifest.

---

## 4. Objects and contracts

### 4.1 The MANIFEST SCHEMA MAP

Every top-level key the loader understands, what governs it, and which subsystem
consumes it. Typed keys become dataclass fields; raw keys are retained verbatim
in `FleetManifest.extra` and read back through `.section(name)`.

| top-level key | typed? | governs | consumed by |
| --- | --- | --- | --- |
| `organisation` | typed `str` | display name, defaults to `tenant_id` | platform user defaults |
| `tenant_id` | typed `str`, **required** | the tenant every seeded row is scoped to | store, kernel, birth receipt |
| `locale_default` / `timezone_default` | typed `str` (`en` / `UTC`) | per-user defaults | platform policy projection ([`boltrig/api/platform_bootstrap.py:31`](../../../boltrig/api/platform_bootstrap.py) `"locale": manifest.locale_default`) |
| `identity` | typed `IdentityConfig` | OIDC trio plus IdP-group to role/scope mappings | `auth_selection`, tenant grant ceiling |
| `models` | typed `ModelsConfig` | endpoints, default, `sensitive_endpoint`, per-model price table | model router, cost, readiness |
| `agents` | typed `NamedAgentsConfig` | the flat durable peer roster and its intake default | fleet pump, named-agent registry |
| `hierarchy` | typed `HierarchyConfig` (deprecated) | pre-flat Chief/Department shape kept for migration | `resolve_named_agents` bridge |
| `ephemeral_runtimes` | typed tuple | short-lived child agent capabilities | spawner, capability reconciliation |
| `spawn_rules` | typed tuple | intent-tag routing policy | `fleet/spawn_policy.py` |
| `adapters` | typed tuple | integrations plus their credential refs | adapter registry, credential seam |
| `hitl` | typed `HitlConfig` | approval channel, timeout, escalation, always-blocking verbs | kernel approval gate |
| `development_posture` | typed `DevelopmentPosture` | the declared four-eyes independence suspension | `kernel/hitl_response_auth.py` |
| `network` | typed `NetworkConfig` | air-gap, proxy, CA bundle, domain allow/block | shared egress guard (process-wide) |
| `privacy` | typed `PrivacyConfig` | PII redaction, residency, retention, redact fields | platform privacy policy |
| `chat` | typed `ChatConfig` **and** retained raw | bare-turn skills, attachment caps, SSE heartbeat, compaction, pagination | `fleet/chat.py` |
| `stack` | raw | the declared v2 component map | `doctor_stack_state.needs_browser_cli` |
| `runtimes` | raw | model-gateway base URL, TTL, health, model profiles | `export_runtime_environment`, doctor retired-runtime check |
| `mcp` | raw | expose the kernel as MCP, consume external MCP servers | `_register_consumed_mcp` |
| `memory` | raw | memory engine, projections, fanout, typed planes, retention | `memory/bootstrap.py`, doctor memory posture |
| `knowledge` | raw | vault kind, providers, Cognee root | `knowledge/register_knowledge` |
| `distill` | raw | nightly sleep distillation sidecar and base pin | `distill/bootstrap.py` |
| `browser_cli` | raw | browser automation enable plus cloud policy | `export_runtime_environment`, `needs_browser_cli` |
| `evaluation` | raw | eval suites | eval runner (declared, retained) |
| `notifications` | raw | per-kind default channels | notification routing |
| `personal_agents` | raw | delegated personal-agent defaults | personal agents |
| `mastra` | raw | orchestration contract seam (inert) | none reached in this tree |
| `langfuse` | raw | observability sink endpoint and key refs | observability |
| `reconcile` | raw | `allow_bulk_deactivate` override | `manifest_reconcile._allow_bulk` |

The raw retention list is a CLOSED fourteen-name tuple
([`boltrig/config/manifest.py:862`](../../../boltrig/config/manifest.py) `"extra={k: doc[k] for k in ("`).
A top-level key outside both the typed set and that tuple is silently dropped at
load: `section()` returns `{}` for it
([`boltrig/config/manifest.py:394`](../../../boltrig/config/manifest.py) `"def section(self, name: str) -> dict[str, Any]:"`).
That is the mechanism behind RISK-1 below.

### 4.2 The typed dataclasses

All are `@dataclass(frozen=True)`. Fields and defaults, as built:

- `CredentialRef(id, store="env", ref="", kind="api_key")`. `as_ref()` emits
  `{store, ref or id, kind}`; the material never enters the manifest
  ([`boltrig/config/manifest.py:44`](../../../boltrig/config/manifest.py) `"A reference to secret material - never the material itself"`).
- `IdentityConfig(provider="oidc", issuer, audience, jwks_uri, metadata_url, role_mappings=())`.
  `provider: saml` raises at load
  ([`boltrig/config/manifest.py:505`](../../../boltrig/config/manifest.py) `"identity.provider 'saml' is not implemented"`).
- `ModelsConfig(endpoints=(), default=None, sensitive_endpoint=None, prices={})`.
  A price is a float or an `{input, output}` mapping in micros per token; a
  negative or unparseable rate is dropped rather than failing load
  ([`boltrig/config/manifest.py:534`](../../../boltrig/config/manifest.py) `"A NEGATIVE rate is dropped - a price must never become a credit"`).
- `BudgetConfig(token_limit, cost_limit_micros, hard_stop=True, window="run")`;
  window vocabulary closed to `run|daily|monthly` in `__post_init__`.
- `NamedAgentConfig(name, address, runtime="codex", model_endpoint, max_depth=3, supported_skills=("*",), cost_tier="standard", scope_id, budget, purpose="", brief="")`.
- `NamedAgentsConfig(default, members)`; `__post_init__` refuses duplicate names
  or addresses and refuses a `default` that is not a declared address.
- `HierarchyTier` / `HierarchyConfig`: the deprecated pre-flat shape, kept so an
  existing deployment migrates without a flag day.
- `EphemeralRuntime(name, runtime="codex", supported_skills=("*",), max_depth=2, cost_tier="cheap", model_endpoint)`.
- `AdapterConfig(id, runtime="http", credential, version="0.1.0", source="builtin", module_ref)`;
  `module_ref` defaults from the six-entry `_BUILTIN_MODULES` table
  ([`boltrig/config/manifest.py:32`](../../../boltrig/config/manifest.py) `"_BUILTIN_MODULES: dict[str, str] = {"`).
- `HitlConfig(primary_channel="slack", notify_via=(), approval_timeout_seconds=86400, escalation_chain=(), blocking_verbs=())`.
- `NetworkConfig(air_gapped=False, https_proxy, ca_bundle, allowed_domains=(), blocked_domains=())`
  plus `as_egress_config()`, the one shape the shared egress guard consumes.
- `PrivacyConfig(pii_redaction=False, data_residency, retention_days, redact_fields=())`.
- `ChatConfig`: see 4.3.
- `FleetManifest`: the aggregate, plus `section()`, `role_mappings`,
  `blocking_verbs()` and `tenant_grants()`.

### 4.3 ChatConfig and the tighten-only cap contract

`ChatConfig` carries seven numeric ceilings whose CODE default is the maximum a
manifest may express. `_tighten_cap(default, raw)` clamps a supplied value into
`[0, default]` and keeps the default on absent or malformed input
([`boltrig/config/manifest.py:743`](../../../boltrig/config/manifest.py) `"def _tighten_cap(default: int, raw_value: Any) -> int:"`).

| knob | manifest path | code default | direction |
| --- | --- | --- | --- |
| `max_attachments` | `chat.attachments.max_count` | 8 | tighten-only |
| `max_attachment_bytes` | `chat.attachments.max_bytes` | 262144 | tighten-only |
| `max_total_attachment_bytes` | `chat.attachments.max_total_bytes` | 1048576 | tighten-only |
| `compaction_threshold` | `chat.compaction.threshold` | 40 | tighten-only |
| `compaction_keep_recent` | `chat.compaction.keep_recent` | 12 | tighten-only |
| `conversation_page_size` | `chat.pagination.page_size` | 25 | tighten-only |
| `conversation_max_page_size` | `chat.pagination.max_page_size` | 100 | tighten-only |
| `continuity_tool_name_chars` | `chat.tool_work.name_chars` | 64 | tighten-only |
| `continuity_tool_pairs_per_turn` | `chat.tool_work.pairs_per_turn` | 10 | tighten-only |
| `heartbeat_seconds` | `chat.heartbeat_seconds` | 15.0 | **honoured as given** |
| `default_capability` | `chat.default_capability` | `None` (fail-closed) | free |
| `skills_by_role` / `default_skills` | `chat.skills_by_role` / `chat.default_skills` | `{}` / `()` (fail-closed) | free |

`heartbeat_seconds` is the one numeric knob that is not tighten-only: a manifest
may set any float and a value at or below zero disables the heartbeat
([`boltrig/config/manifest.py:813`](../../../boltrig/config/manifest.py) `"def _parse_heartbeat(raw_value: Any) -> float:"`).

### 4.4 The approval-window floor

`APPROVAL_TIMEOUT_SECONDS_FLOOR = 86400`
([`boltrig/config/manifest.py:213`](../../../boltrig/config/manifest.py) `"APPROVAL_TIMEOUT_SECONDS_FLOOR = 86400"`)
is carried at both sites so a manifest with no `hitl` block and one whose block
omits the key resolve identically. It is a floor on the DEFAULT only: a stated
value passes through `int()` unclamped
([`boltrig/config/manifest.py:716`](../../../boltrig/config/manifest.py) `"approval_timeout_seconds=int("`),
which the test suite asserts deliberately
([`tests/security/test_operator_seat_boundary.py:206`](../../../tests/security/test_operator_seat_boundary.py) `"The floor moves the DEFAULT, never a tenant's deliberate statement"`).

### 4.5 Settings

`Settings` is a frozen dataclass over `os.environ`, "one per process, read once
at boot"
([`boltrig/config/settings.py:27`](../../../boltrig/config/settings.py) `"Immutable process settings (one per process, read once at boot)"`).
It carries 24 fields and three derived predicates: `oidc_configured`,
`cf_access_configured`, `session_auth_configured`. It is NOT a singleton:
`load_settings()` is called freshly at each composition site
(`select_principal_resolver`, `_build_shared_codex_config`, `chat_factory`,
`_build_platform_services`), so a mid-process environment mutation would be
observed by later callers. Nothing in the tree mutates those keys after boot
except `export_runtime_environment`, which runs before every one of them.

---

## 5. Control flow

### 5.1 `load_manifest(path, env=None)`

1. `open(path)` then `yaml.safe_load(fh) or {}`
   ([`boltrig/config/manifest.py:833`](../../../boltrig/config/manifest.py) `"raw_doc = yaml.safe_load(fh) or {}"`).
   FAILURE: `FileNotFoundError` propagates; `config-validate` maps it to exit 2
   and every composition root guards with an existence check first.
   A YAML syntax error propagates as `yaml.YAMLError`.
2. `_interpolate(raw_doc, environ)` walks dicts, lists and strings and
   substitutes `${VAR}` / `${VAR:-default}`
   ([`boltrig/config/manifest.py:438`](../../../boltrig/config/manifest.py) `"_VAR = re.compile(r"`).
   FAILURE: there is none. An unset variable with no default becomes the EMPTY
   STRING
   ([`boltrig/config/manifest.py:452`](../../../boltrig/config/manifest.py) `return env.get(name, default if default is not None else "")`).
   The `${VAR:?message}` form Compose uses is not matched by the regex and is
   left in the document as a literal string.
3. `tenant_id = str(doc["tenant_id"])`. FAILURE: `KeyError` on a manifest with
   no `tenant_id`. This is the only mandatory top-level key.
4. Mutual exclusion: declaring both `agents` and `hierarchy` raises
   ([`boltrig/config/manifest.py:838`](../../../boltrig/config/manifest.py) `"manifest must declare agents or legacy hierarchy, not both"`).
5. Each section is parsed by its `_parse_*` helper. FAILURE branches, in the
   order a document meets them:
   - `identity.provider == "saml"` raises `ValueError` (SEC-68).
   - `agents` with an unknown key, an empty `named` list, a bad address slug, a
     name over 128 chars, a runtime outside `{codex, script, python-script}`,
     0 or more than 64 skills, a `max_depth` outside 1..5, a bad `scope_id`, a
     purpose over 500 or brief over 8000 chars: all raise `ValueError`
     ([`boltrig/config/manifest_agents.py:34`](../../../boltrig/config/manifest_agents.py) `"agents.named must declare at least one named agent"`).
   - `NamedAgentsConfig.__post_init__` raises on duplicate names or addresses and
     on a `default` that names no declared address.
   - `spawn_rules` is a CLOSED schema: at most 128 rules, unique names, the four
     required fields `name/priority/match/capability`, `match` closed to
     `intent_tags`, bounded priority 0..1000 and depth 1..10. Any breach raises
     `SpawnRuleValidationError`
     ([`boltrig/config/spawn_rules.py:184`](../../../boltrig/config/spawn_rules.py) `"is missing required fields: "`).
   - `cost_tier` outside `{cheap, standard, expensive}` raises through
     `validate_cost_tier`; `budget.window` outside `{run, daily, monthly}` raises
     in `BudgetConfig.__post_init__`.
   - A malformed model PRICE does NOT raise: the entry is dropped whole so the
     model falls back to its cost tier rather than billing zero
     ([`boltrig/config/manifest.py:560`](../../../boltrig/config/manifest.py) `"An entry with NO usable leg is dropped whole"`).
   - A malformed `development_posture.expires_at` or `covers` does NOT raise: it
     yields `None` / `()`, which `posture_block` refuses, so the failure mode is
     full four-eyes.
6. `extra` is populated from the fourteen-name allow-list and the frozen
   `FleetManifest` is returned.

### 5.2 Manifest discovery

`_find_manifest()` returns the first existing path from
`BOLTRIG_MANIFEST`, `/app/manifest.yaml`, `manifest.yaml`, `manifest.example.yaml`
([`boltrig/api/bootstrap.py:49`](../../../boltrig/api/bootstrap.py) `"_MANIFEST_CANDIDATES = ("`),
reading the environment variable LIVE rather than at import so a test or a
dynamic config can set it after import
([`boltrig/api/bootstrap.py:57`](../../../boltrig/api/bootstrap.py) `"def _find_manifest() -> str | None:"`).
No manifest at all is a supported state: the process boots a minimal demo tenant
named `default`.

The shipped example is a real fallback candidate, but only outside a container:
neither `deploy/kernel.Dockerfile` nor `deploy/fleet.Dockerfile` copies
`manifest.example.yaml` into the image (bounded:
`grep -rn "manifest.example" deploy/ docker-compose.yml Makefile scripts/`,
2026-08-24, pinned tree; the only hits are a comment in `docker-compose.yml` and
three gate scripts). Compose bind-mounts the operator's file read-only:
`./manifest.yaml:/app/manifest.yaml:ro`
([`docker-compose.yml:174`](../../../docker-compose.yml) `"./manifest.yaml:/app/manifest.yaml:ro"`).

### 5.3 THE MANIFEST SNAPSHOT: who loads it and how many exist

`compose_process_model_runtime` is the single composition helper. It finds one
path, loads one snapshot, exports the manifest's non-secret runtime policy into
the process environment, and only then builds the Codex config and the model
catalogue, so both see the same gateway route for the life of the process
([`boltrig/api/model_runtime_composition.py:26`](../../../boltrig/api/model_runtime_composition.py) `"manifest_path = find_manifest()"`).

`build_kernel_async` takes `manifest_snapshot` as a sentinel-defaulted parameter.
When a snapshot is supplied it is used verbatim and the file is NOT re-read
([`boltrig/api/bootstrap.py:429`](../../../boltrig/api/bootstrap.py) `"if manifest_snapshot is _MANIFEST_UNSET:"`);
when it is omitted the standalone convenience path re-finds and re-loads. If the
caller also passed a `sensitive_endpoint_id` that disagrees with the snapshot's,
composition ABORTS
([`boltrig/api/bootstrap.py:440`](../../../boltrig/api/bootstrap.py) `"sensitive model routing changed during process composition"`).

Snapshot count per serving process, as built:

| process | reads of the manifest FILE | where |
| --- | --- | --- |
| API (`uvicorn boltrig.api.asgi:app`) | **three** | composition (typed), chat factory (typed), AdminConfig (raw) |
| standalone fleet worker (`python -m boltrig.api.worker`) | one | [`boltrig/api/worker.py:365`](../../../boltrig/api/worker.py) `"manifest_path, manifest_snapshot, codex_config, model_catalogue = ("` |
| Hatchet worker (`python -m boltrig.fleet.hatchet_worker`) | one | [`boltrig/fleet/hatchet_bootstrap.py:51`](../../../boltrig/fleet/hatchet_bootstrap.py) `"manifest_path, manifest_snapshot, codex_config, model_catalogue = ("` |
| `boltrig fleet-health` healthcheck | one (separate short-lived process) | [`boltrig/api/fleet_health.py:50`](../../../boltrig/api/fleet_health.py) `"manifest = load_manifest(path)"` |
| `python -m boltrig.fleet.browser_runtime` | one (separate short-lived process) | [`boltrig/fleet/browser_runtime.py:63`](../../../boltrig/fleet/browser_runtime.py) `"return bool(needs_browser_cli(load_manifest(path)))"` |

The API's three reads, in order:

1. **Import time.** `compose_api_app` calls `compose_process_model_runtime` and
   threads that ONE object into the kernel factory, the spawner factory, the
   principal resolver, the platform factory and the birth receipt
   ([`boltrig/api/app_composition.py:74`](../../../boltrig/api/app_composition.py) `"manifest_path, manifest, codex_config, model_catalogue = ("`,
   [`boltrig/api/app_composition.py:124`](../../../boltrig/api/app_composition.py) `"principal_resolver=select_principal_resolver(manifest),"`).
2. **Lifespan startup, chat.** `chat_factory` calls `_find_manifest()` again and
   `load_manifest(...).chat`, inside a bare `except Exception: pass`
   ([`boltrig/api/bootstrap.py:590`](../../../boltrig/api/bootstrap.py) `"chat_cfg = load_manifest(manifest_path).chat"`).
   This is a SECOND typed snapshot, read from whatever the file contains at that
   moment, and a manifest that has become unparseable between import and startup
   silently yields the fail-closed empty `ChatConfig` rather than failing boot.
3. **Lifespan startup, admin.** `AdminConfig(..., path=manifest_path)` opens the
   file and `yaml.safe_load`s it with NO `${ENV}` interpolation
   ([`boltrig/config/admin.py:30`](../../../boltrig/config/admin.py) `with open(path, encoding="utf-8") as fh:`,
   constructed at [`boltrig/api/platform_bootstrap.py:110`](../../../boltrig/api/platform_bootstrap.py) `"admin = AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path)"`).
   The console therefore exports the RAW document with `${VAR}` placeholders
   intact, which keeps secrets out of the export and makes the export a
   deliberately different artefact from the runtime view.

The Hatchet worker takes `chat_config=manifest.chat` from its single snapshot
([`boltrig/fleet/hatchet_bootstrap.py:92`](../../../boltrig/fleet/hatchet_bootstrap.py) `"chat_config=manifest.chat if manifest is not None else None,"`),
so the API is the outlier, not the pattern.

### 5.4 How kernel and pump are kept from splitting

Three mechanisms, in increasing strength:

1. **One snapshot per composition root.** `CODEX-COMPOSITION-1` states that a
   serving process "loads at most one manifest snapshot, then injects that exact
   configuration ... The same snapshot seeds API authentication and kernel policy
   and is the only source manifest overlaid for durable-fleet construction, so a
   file change cannot split kernel and pump routing"
   ([`tests/invariants.yaml:25`](../../../tests/invariants.yaml) `"loads at most one manifest snapshot"`).
   The kernel half is pinned by a test that monkeypatches `load_manifest` to
   raise and asserts `build_kernel_async` never touches it
   ([`tests/unit/test_codex_trusted_composition.py:344`](../../../tests/unit/test_codex_trusted_composition.py) `"test_kernel_uses_the_composition_manifest_snapshot_without_rereading"`).
2. **A composition-time abort on divergent sensitive routing** (5.3 above).
3. **A published per-boot digest.** Each process publishes a
   `BirthProfileReceipt` whose `manifest_generation` is a SHA-256 digest of its
   effective typed manifest
   ([`boltrig/config/birth_profile.py:71`](../../../boltrig/config/birth_profile.py) `"def manifest_generation(manifest: Any) -> str:"`).
   The projection compares every retained instance against the latest API
   receipt and reports `mismatched_startup_liveness_unknown` when
   `manifest_generation` differs
   ([`boltrig/config/birth_profile_projection.py:45`](../../../boltrig/config/birth_profile_projection.py) `evidence_state = "mismatched_startup_liveness_unknown"`).
   This DETECTS a kernel/pump split; nothing refuses to serve on one.

The gap: the API's second and third reads (5.3) never enter any digest, so a
split between the API's kernel policy and the API's own chat policy is invisible
to this mechanism. See RISK-2.

### 5.5 `apply_manifest(kernel, manifest, ...)`

1. `export_runtime_environment(manifest)`
   ([`boltrig/config/manifest_apply.py:209`](../../../boltrig/config/manifest_apply.py) `"export_runtime_environment(manifest)"`).
2. Install the manifest's network posture as the PROCESS-WIDE egress default,
   BEFORE any adapter is built, because module-ref factories are called as bare
   `build()` and have no construction seam to receive it
   ([`boltrig/config/manifest_apply.py:221`](../../../boltrig/config/manifest_apply.py) `"set_default_network_config(network.as_egress_config())"`).
   Only a typed `NetworkConfig` installs; a composition-root stub stays inert.
3. `_permanent_state`: a flat roster returns the manifest unchanged; a legacy
   hierarchy is overlaid from the latest durable `permanent_fleet` revision.
4. `plan_capability_reconciliation` runs BEFORE any write and may raise
   `BulkCapabilityDeactivationError`, aborting the whole apply with nothing
   committed
   ([`boltrig/config/manifest_reconcile.py:127`](../../../boltrig/config/manifest_reconcile.py) `"over_threshold = dropped > max(_MIN_ABSOLUTE_DROP, a_before // 2)"`).
5. `_seed_projection`: upsert model endpoints, set the cost price table, upsert
   declared capabilities, upsert named agents and deactivate absent ones, upsert
   budget policies, set tenant permissions, register the questions verb, seed
   credential refs, and register builtin/module-ref adapters. A module that
   fails to import is logged and SKIPPED so one stale `module_ref` cannot make
   the kernel unbootable
   ([`boltrig/config/manifest_apply.py:135`](../../../boltrig/config/manifest_apply.py) `"except Exception as exc:  # a bad manifest adapter must not kill boot"`).
6. `reconcile_capabilities` soft-deactivates the dropped manifest-sourced
   capabilities through one atomic store statement and writes one audit row per
   deactivation.
7. On a first legacy-hierarchy boot only, record the initial `permanent_fleet`
   `ConfigRevision`.

### 5.6 `export_runtime_environment`

Projects six non-secret manifest values into `os.environ`, each guarded by "only
if the key is not already present", so an explicit process environment always
wins
([`boltrig/config/manifest_runtime.py:25`](../../../boltrig/config/manifest_runtime.py) `if base_url and "BOLTRIG_MODEL_GATEWAY_URL" not in target:`):
`BOLTRIG_MODEL_GATEWAY_URL`, `BOLTRIG_MODEL_GATEWAY_TTL`,
`BOLTRIG_MODEL_GATEWAY_HEALTH`, `BOLTRIG_MODEL_GATEWAY_HEALTH_PATH`,
`BOLTRIG_MODEL_GATEWAY_HEALTH_TIMEOUT`, `BOLTRIG_MODEL_PROFILES` (JSON) and
`BOLTRIG_BROWSER_CLOUD_POLICY`. It is deliberately secret-free.

### 5.7 Release mode

`BOLTRIG_RELEASE_MODE` admits exactly `core` or `full`, with no trimming and no
case folding
([`boltrig/release_mode.py:9`](../../../boltrig/release_mode.py) `VALID_RELEASE_MODES = frozenset({"core", "full"})`).
`configured_release_mode` preserves ABSENCE as "no override" (returns `None`)
and validates only a present value, so a decorated value such as `"core "` or
`"CORE"` raises rather than being normalised.

What it changes:

- **Readiness and doctor.** `core` DISABLES the Codex runtime check outright
  (`status: disabled, reason: core_release_mode`), and `core` together with
  `BOLTRIG_CODEX_TRUSTED=1` is a hard `release_mode_conflict` failure
  ([`boltrig/api/codex_readiness.py:43`](../../../boltrig/api/codex_readiness.py) `if mode == "core":`).
  An invalid value is `invalid_release_mode`, a failure, not a default.
- **Edge posture.** A `full` release with no packaged-desktop origin in
  `BOLTRIG_CORS_ORIGINS` is a doctor FAIL
  ([`boltrig/api/doctor_edge.py:42`](../../../boltrig/api/doctor_edge.py) `if env.get("BOLTRIG_RELEASE_MODE") == "full" and not configured_desktop:`).
- **The release Compose overlay.** Four services (`kernel`, `fleet-worker`,
  `browser-executor`, `hatchet-worker`) each bind the variable with Compose's
  required form, and the merged-model validator refuses a missing, decorated or
  DISAGREEING binding
  ([`scripts/validate_release_compose.py:69`](../../../scripts/validate_release_compose.py) `"if len(set(bound_modes.values())) != 1:"`).
- **The release workflow.** `core` records `desktop=omitted`,
  `hosted_agent=disabled`, `local_desktop_agent=omitted` in
  `release-metadata.json`, skips all three desktop candidates, and refuses any
  desktop asset on the draft; `full` requires exactly three desktop evidence
  files and three updater fragments. The metadata is written once and a later
  run that would change the mode or commit is refused
  ([`.github/workflows/release.yml:289`](../../../.github/workflows/release.yml) `"draft release metadata differs; refusing to change release mode or commit"`).
  Both modes keep the four-image signature, SBOM and provenance gates (IAC-005).

Release mode does NOT change any runtime code path other than the readiness and
doctor projections above. Bounded: `rg -n "BOLTRIG_RELEASE_MODE|configured_release_mode|validate_release_mode|RELEASE_MODE_ENV"`
over the pinned tree, 2026-08-24, returns only `release_mode.py`,
`codex_readiness.py`, `doctor_codex.py`, `doctor_edge.py`, the two scripts, the
release overlay, the Makefile, the workflow and their tests.

### 5.8 Product name

The deployment's name is DERIVED from the active addon set, never from a build
flag, because a name compiled into a bundle is invisible until someone looks at
the screen
([`boltrig/branding.py:39`](../../../boltrig/branding.py) `"return OPBOX_AGENTS if any(a.name == _OPBOX_ADDON for a in active) else BOLTRIG"`).
`BOLTRIG_ADDONS` naming an unregistered addon RAISES at import of the ASGI
module, so a typo is a startup failure rather than a silently missing
integration
([`boltrig/addons/__init__.py:167`](../../../boltrig/addons/__init__.py) `"names unregistered addon(s)"`).

---

## 6. Data

This subsystem owns no table of its own. It writes to four:

| table | what config writes | where |
| --- | --- | --- |
| `config_revisions` | `kind='manifest_section'` rows on every Admin section edit and rollback; `kind='permanent_fleet'` on first legacy-hierarchy boot | [`boltrig/config/admin.py:51`](../../../boltrig/config/admin.py) `tenant_id=self._tenant, kind="manifest_section", ref=name,` |
| `credential_refs` | one row per manifest adapter credential, holding `{store, ref, kind}` and never material; envelope-sealed at the store seam | [`boltrig/config/manifest_apply.py:106`](../../../boltrig/config/manifest_apply.py) `"\"set_credential_ref\","` |
| `agent_capabilities` | one row per ephemeral runtime and named agent, `source='manifest'`; absent names soft-deactivated | [`boltrig/config/manifest_reconcile.py:148`](../../../boltrig/config/manifest_reconcile.py) `"deactivate_absent_manifest_capabilities("` |
| `birth_profile_receipts` | one bounded per-boot receipt per process kind, opaque digests only | [`boltrig/config/birth_profile.py:201`](../../../boltrig/config/birth_profile.py) `"async def record_birth_profile_startup("` |

`config_revisions` is declared in the baseline schema with
`kind TEXT NOT NULL, -- manifest_section|skill|workflow|noun|verb|binding|adapter`
([`boltrig/store/schema.sql:766`](../../../boltrig/store/schema.sql) `"kind        TEXT NOT NULL,    -- manifest_section|skill"`).

**Only one manifest section round-trips from a revision back into runtime
behaviour.** `spawn_rules` is resolved per spawn from the latest
`manifest_section/spawn_rules` revision, falling back to the process-start
manifest when there is none
([`boltrig/config/spawn_rule_revisions.py:22`](../../../boltrig/config/spawn_rule_revisions.py) `source="process_start_manifest",`).
Every other section edit changes only `AdminConfig`'s in-memory document and the
revision history: bounded search for readers of
`list_config_revisions(..., "manifest_section", ...)` returns exactly
`admin.history` and `spawn_rule_revisions.effective_spawn_rules`
(`rg -n "manifest_section" --glob '!docs/**'`, 2026-08-24, pinned tree).

Retention and encryption for these tables are specified by the store and audit
areas; nothing in this area sets a retention policy other than the manifest's
declarative `privacy.retention_days` and `memory.retention_days`, which are
consumed elsewhere.

---

## 7. Configuration surface

### 7.1 ENV VAR INVENTORY, grouped by subsystem

Defaults are the value the CODE uses when the variable is unset. "blast radius"
is what goes wrong when the value is wrong, not merely absent.

**Datastores and process identity**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `DATABASE_URL` | `None` (in-memory store) | wrong DSN means a silent in-memory store in dev and a production doctor FAIL; a placeholder value is a doctor FAIL by fragment match ([`boltrig/api/doctor.py:196`](../../../boltrig/api/doctor.py) `"DATABASE_URL still contains a placeholder."`) |
| `REDIS_URL` | `None` | shared rate-limit counter and event relay degrade to in-process; production readiness requires the Redis-backed relay with no in-memory fallback |
| `BOLTRIG_EVENT_RELAY_NAMESPACE` | `default` | two deployments sharing one Redis cross-deliver run events; replicas of one deployment that disagree lose events |
| `POSTGRES_USER` / `POSTGRES_DB` | `boltrig` (genesis) | container bootstrap only |
| `POSTGRES_PASSWORD` | none, Compose refuses to start without it | must match the password segment of `DATABASE_URL` (SEC-69); a weak or placeholder value is a doctor FAIL |
| `BOLTRIG_RLS` | off | ON without the SQL overlay does nothing; the overlay without the flag returns ZERO ROWS on every read (`.env.example:396` `"sequence is not reorderable"`) |

**Secrets and sealing**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `SECRET_STORE` | `env` | `env` in production is a doctor WARN; an unknown value is not validated here |
| `BOLTRIG_AUDIT_HMAC_KEY` | in-source `dev-insecure-audit-key` | a placeholder under a production signal is FATAL at boot; without a production signal it WARNS every boot and the audit chain is forgeable by anyone with the repo ([`boltrig/api/boot_guards.py:58`](../../../boltrig/api/boot_guards.py) `"if signal is not None and is_placeholder_secret(key):"`). Read at IMPORT ([`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `_HMAC_KEY = os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()`), so a later change has no effect |
| `BOLTRIG_AUDIT_HMAC_RETIRED` | unset | a rotation not recorded here makes every pre-rotation audit row fail verification permanently |
| `BOLTRIG_SEAL_KEY` | in-source `dev-insecure-seal-key` | unset or default under a production signal is FATAL; otherwise credential refs at rest are sealed with a public key ([`boltrig/store/sealing.py:173`](../../../boltrig/store/sealing.py) `"if signal is not None and (not key or key == _DEV_SEAL_KEY):"`) |
| `BOLTRIG_SEAL_KEY_PREVIOUS` | unset | decrypt-only rotation leg; absent during rotation makes old rows unreadable |
| `BOLTRIG_DEVICE_LEASE_SIGNING_KEY` | unset | device enrollment and lease routes fail closed with `device_leases_unavailable`; the rest stays live |

**Identity and the auth door** (precedence: session, then Cloudflare Access, then OIDC, then dev auth, then deny-all, [`boltrig/api/auth_selection.py:104`](../../../boltrig/api/auth_selection.py) `"if settings.session_auth_configured:"`)

| var | default | blast radius if wrong |
| --- | --- | --- |
| `BOLTRIG_AUTH_MODE` | unset | `session` selects the first-party session resolver AHEAD of Cloudflare Access and OIDC; a typo silently falls through to the next posture |
| `BOLTRIG_SESSION_TENANT` | the default tenant | session users land in the wrong tenant |
| `BOLTRIG_SESSION_COOKIE_SECURE` | **true** | an explicit false under session auth puts the bearer cookie on plaintext HTTP; doctor FAILs in production |
| `CF_ACCESS_TEAM_DOMAIN` + `CF_ACCESS_AUD` | unset | both set selects Cloudflare Access; only one set is a doctor FAIL in production but does NOT block boot |
| `CF_ACCESS_ROLE_MAP` | `{}` | invalid JSON logs an error and is treated as empty, which is deny-by-default |
| `CF_ACCESS_DEFAULT_ROLE` | `none` | any other value grants an authenticated-but-unmapped email a role |
| `CF_ACCESS_TENANT` | the default tenant | Access users land in the wrong tenant |
| `OIDC_ISSUER` / `OIDC_AUDIENCE` / `OIDC_JWKS_URI` | unset | all three plus a manifest trio that DIFFERS refuses boot; a partial manifest trio refuses boot; a partial env trio simply does not select OIDC and falls through |
| `BOLTRIG_DEV_AUTH` | off | ON with any production signal is FATAL at boot (IAM-09); ON without one trusts `x-boltrig-*` headers with no verification |
| `AGENT_SP_ID` | `boltrig-agent` | the service principal agents act as for non-delegated calls |

**Network and edge**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `AIR_GAPPED` | `false` | true forbids all outbound adapter traffic; the manifest's `network.air_gapped` is OR-ed with it in doctor |
| `HTTPS_PROXY` / `https_proxy` | unset | adapter egress bypasses the corporate proxy |
| `CA_BUNDLE` | unset | TLS verification against a private CA fails |
| `NO_PROXY` | the compose service list | a missing internal name routes internal traffic through the proxy |
| `BOLTRIG_ALLOWED_HOSTS` | `*` | `*` under a production signal is FATAL ([`boltrig/kernel/web_security.py:299`](../../../boltrig/kernel/web_security.py) `"FATAL: BOLTRIG_ALLOWED_HOSTS is '*' in production."`) |
| `BOLTRIG_CORS_ORIGINS` | same-origin | `*` is a doctor FAIL; a `full` release without a Tauri origin is a doctor FAIL |
| `BOLTRIG_MAX_BODY_BYTES` | 1048576 | a non-positive or unparseable value is a doctor WARN and falls back to the default |
| `BOLTRIG_TRUST_FORWARDED_PREFIX` | off | ON where no proxy strips a prefix lets a client set its own cookie scope |
| `BOLTRIG_DOMAIN` | unset | production doctor cannot confirm TLS overlay intent (WARN) |

**Models and the gateway**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `BOLTRIG_MODEL_GATEWAY_URL` | unset, or the manifest's `runtimes.gateway.base_url` | unset leaves the gateway seam inert and standard traffic unrouted; a wrong URL breaks every standard-data turn. Sensitive data never routes here |
| `BOLTRIG_MODEL_GATEWAY_TTL` | 900 | prompt-cache warmth only |
| `BOLTRIG_MODEL_GATEWAY_HEALTH` / `_PATH` / `_URL` / `_TIMEOUT` | off, `/health`, derived, 0.75 | a bad health URL makes platform status report a false negative |
| `BOLTRIG_MODEL_GATEWAY_KEY` | unset | the kernel-only upstream key the trusted Codex proxy injects |
| `BOLTRIG_MODEL_PROFILES` | unset, or the manifest's `runtimes.gateway.model_profiles` JSON | governs advertised realtime model profiles |
| `BOLTRIG_DEFAULT_MODEL` | **empty string** (via `${BOLTRIG_DEFAULT_MODEL:-}` in the template) | the shipped `standard` endpoint has an empty model name; see RISK-5 |
| `BOLTRIG_LOCAL_MODEL` / `BOLTRIG_LOCAL_MODEL_URL` | empty / `http://local-model:8000/v1` | the sensitive endpoint's model identity |

**Codex runtime**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `BOLTRIG_CODEX_TRUSTED` | off | ON constructs the loopback-proxy Codex runtime; refuses under any production signal; conflicts with `BOLTRIG_RELEASE_MODE=core` at readiness |
| `BOLTRIG_CODEX_BINARY` / `BOLTRIG_CODEX_STACK_ROOT` | unset | either missing keeps the runtime OFF and degrades to a deterministic script run, silently |
| `BOLTRIG_CODEX_MODEL` | `glm-4.6` | the model the read-only cell pins |
| `BOLTRIG_CODEX_LEDGER` | off | ON constructs the shadow admission stack, execution-neutral (SEC-172) |
| `BOLTRIG_LOCAL_CODEX_BIN` | unset | dev-only absolute path; signed release builds ignore it |

**Durability and janitors**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `HATCHET_CLIENT_TOKEN` | unset | set makes readiness probe the engine and fail closed if unreachable |
| `HATCHET_CLIENT_TLS_STRATEGY` | `none` in the template | anything else against the bundled hatchet-lite dies with an SSL handshake error and execution silently drops to the non-durable local executor. Two production stacks ran that way unnoticed |
| `BOLTRIG_REQUIRE_DURABLE` | off | ON makes a missing durable engine a readiness failure |
| `BOLTRIG_HATCHET_HEALTH` | off | ON probes the engine explicitly |
| `BOLTRIG_HITL_EXPIRY_INTERVAL` | 60.0 s | `<= 0` disables the sweep; a malformed value falls back to the default, never a boot crash |
| `BOLTRIG_RETENTION_INTERVAL` | 3600.0 s | same contract; `<= 0` disables the retention janitor |
| `BOLTRIG_AUDIT_ANCHOR_INTERVAL` / `BOLTRIG_AUDIT_OUTBOX_INTERVAL` | daily / see module | `<= 0` disables; the worker logs which it did |
| `BOLTRIG_WORKFLOW_SCHEDULER_INTERVAL` | module default, clamped at 0 | scheduling latency |

**Readiness and stack tools**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `BOLTRIG_READINESS_TIMEOUT` | 0.75, clamped 0.05..10 | too low reports false negatives on a slow box |
| `BOLTRIG_READINESS_CACHE_TTL` | 1 | coalescing window for unauthenticated probes |
| `BOLTRIG_REQUIRE_STACK_TOOL_HEALTH` | off outside production | ON in development demands live fleet receipts |
| `BOLTRIG_STACK_TOOL_RECEIPT_TTL` / `_HEARTBEAT_INTERVAL` / `_PROBE_TIMEOUT` | 30 / 10 / 4 | cross-bounded; an interval above the TTL guarantees stale receipts |
| `BOLTRIG_BROWSER_CLI_HOME` / `_BIN` | `/var/lib/boltrig/browser-cli`, `browser-use` | unset is a production doctor FAIL when browser automation is declared; a personal profile path is a FAIL |
| `BOLTRIG_FLEET_BROWSER_CLI_HOME` / `BOLTRIG_HATCHET_BROWSER_CLI_HOME` | compose-provided | making the two equal collides two long-lived Chromium profiles |

**Product shape**

| var | default | blast radius if wrong |
| --- | --- | --- |
| `BOLTRIG_MANIFEST` | unset | overrides manifest discovery; a wrong path silently falls through to the next candidate |
| `BOLTRIG_ADDONS` | unset (`()`) | an unregistered name RAISES at ASGI import; `opbox` changes the product name, the chat bearer seal and the model harness |
| `BOLTRIG_OBO_ADAPTER_ID` | `opbox` | only when the consumed server has a different adapter id |
| `BOLTRIG_RELEASE_MODE` | absent means no override | see 5.7; a decorated value is `invalid_release_mode`, never a default |
| `BOLTRIG_DESKTOP_HANDS` | off | ON registers the governed `desktop.*` verbs and the `/v1/hands` pull surface |
| `BOLTRIG_EMOTION` | off | ON registers the Familiar adapter (desktop only) |
| `BOLTRIG_REFLECT` | off | ON makes terminal work items write a `lesson` memory automatically, retained for `memory.retention_days` |
| `BOLTRIG_CONTINUITY` | `1` | `0` restores single-message prompts exactly |
| `BOLTRIG_PRODUCTION`, `ENV`, `BOLTRIG_ENV`, `APP_ENV` | all unset | the production/development classification; see 9.1 |
| `BOLTRIG_LOG_LEVEL` | `INFO` | boot records are discarded below it |

**Documented in `.env.example` but read by nothing in `boltrig/` or `services/`**:
`BOLTRIG_TEST_DATABASE_URL`, `BOLTRIG_TEST_REDIS_URL` (read by the test suite),
`BOLTRIG_DESKTOP_DOWNLOAD_URL` (a UI build arg), `BOLTRIG_LOCAL_CODEX_BIN` (the
Tauri build).

**Read by shipped code and documented NOWHERE** in `.env.example`,
`docker-compose.yml` or `deploy/`: thirty-seven names, including every janitor
interval, `BOLTRIG_AUDIT_HMAC_RETIRED`, `BOLTRIG_AUDIT_KMS_KEY_ID`,
`BOLTRIG_AUDIT_TSA_URL`, `BOLTRIG_AUTH_MODE`, `BOLTRIG_SESSION_TENANT`,
`BOLTRIG_SESSION_COOKIE_SECURE`, `BOLTRIG_MANIFEST`, `BOLTRIG_TENANT_ID`,
`BOLTRIG_MODEL_PROFILES`, `BOLTRIG_INIT_PASSWORD`, `BOLTRIG_CLI_TOKEN`,
`BOLTRIG_LOG_LEVEL` and `BOLTRIG_RELEASE_MODE` itself (bounded:
`comm -23` of `rg -o '\bBOLTRIG_[A-Z0-9_]+' boltrig/ services/` against the same
over `.env.example docker-compose.yml deploy/`, `LC_ALL=C`, 2026-08-24, pinned
tree). Three of those (`BOLTRIG_AUTH_MODE`, `BOLTRIG_SESSION_TENANT`,
`BOLTRIG_SESSION_COOKIE_SECURE`) are the entire first-party login posture and
are written by `genesis.sh` rather than documented in the template.

### 7.2 `${ENV}` references inside the shipped manifest

Sixteen variables are referenced by `manifest.example.yaml`. Six of them appear
nowhere in `.env.example`: `BOLTRIG_DEFAULT_MODEL`, `BOLTRIG_LOCAL_MODEL`,
`BOLTRIG_LOCAL_MODEL_URL`, `BOLTRIG_ORGANISATION`, `BOLTRIG_TENANT_ID` and
`LINEAR_MCP_TOKEN` (bounded: the sixteen `${VAR}` names extracted from
`manifest.example.yaml` and grepped against `.env.example`, 2026-08-24). All six
have a `:-` default or sit in a comment, so the template still parses; the
consequence is silence rather than failure. See RISK-5.

---

## 8. PROCESS

### 8.1 Bringing a box up from a fresh clone

The canonical path is `genesis.sh`, one run, idempotent and resume-safe.

1. `cp .env.example .env` (genesis does it if absent) and
   `cp manifest.example.yaml manifest.yaml`
   ([`genesis.sh:102`](../../../genesis.sh) `"[ -f manifest.yaml ] || cp manifest.example.yaml manifest.yaml"`).
2. Genesis MINTS the blank internal secrets, filling only empty values:
   `POSTGRES_PASSWORD`, `BOLTRIG_AUDIT_HMAC_KEY`
   ([`genesis.sh:104`](../../../genesis.sh) `"gen_secret BOLTRIG_AUDIT_HMAC_KEY"`)
   and an Ed25519 seed for `BOLTRIG_DEVICE_LEASE_SIGNING_KEY`.
   It does NOT mint `BOLTRIG_SEAL_KEY`. See RISK-4.
3. Genesis rewrites `DATABASE_URL` so its credential segment matches
   `POSTGRES_USER`/`POSTGRES_PASSWORD` (SEC-69) and pins
   `BOLTRIG_AUTH_MODE=session`, `BOLTRIG_DEV_AUTH=0`,
   `HATCHET_CLIENT_TLS_STRATEGY=none`, the Bifrost port and the gateway URL.
4. Datastores, the Hatchet database, the token mint, then the one-shot
   `boltrig initiate` founding superadmin.

The manual path is the README's two copies plus `make up`
([`README.md:131`](../../../README.md) `"cp manifest.example.yaml manifest.yaml"`).
A manual operator gets NEITHER minted secret and must fill both by hand.

### 8.2 Changing configuration

- **A manifest edit** is a file edit plus a process restart. Nothing reloads a
  manifest in place; every snapshot is taken at composition (5.3).
- **A section edit through the Admin Console** writes a versioned
  `ConfigRevision` and changes `AdminConfig`'s in-memory document. Only
  `spawn_rules` reaches the runtime from there; everything else is
  export-and-history only (section 6). `hierarchy` is refused by
  `update_section` and `rollback` and is governed by the permanent-fleet
  authoring surface instead
  ([`boltrig/config/admin.py:44`](../../../boltrig/config/admin.py) `"hierarchy is governed by the permanent-fleet authoring surface"`).
- **An `.env` edit** is a restart, and for Compose specifically a `down`/`up`:
  `docker restart` does not reload an env file.

### 8.3 Pre-flight before a deploy: `config-validate`

Run the CANDIDATE IMAGE against the TARGET's manifest before swapping:

    docker run --rm -v /path/to/manifest.yaml:/m.yaml:ro <image> \
        boltrig config-validate /m.yaml

Exit codes are a contract: 0 parses, 1 the shipping loader REFUSED it (the
exception type is printed because a `SpawnRuleValidationError`, a YAML parse
error and a missing key want different fixes), 2 operator error (no path, or no
such file)
([`boltrig/api/config_validate.py:62`](../../../boltrig/api/config_validate.py) `"return 1"`).
The command exists because a 26-migration database pre-flight passed and the
deploy still crash-looped on
`SpawnRuleValidationError: spawn_rules[0] is missing required fields: priority`
([`boltrig/api/config_validate.py:7`](../../../boltrig/api/config_validate.py) `"SpawnRuleValidationError: spawn_rules[0] is missing required fields: priority"`).

**Its documented false-red does not exist.** The module says a bare run "can fail
on an unset variable that IS set in production" and that "the message names the
variable"
([`boltrig/api/config_validate.py:32`](../../../boltrig/api/config_validate.py) `"run bare, a manifest can fail on an"`).
The loader cannot do that: an unset `${VAR}` with no default becomes the empty
string and no error is raised (5.1 step 2). `tests/unit/test_readiness.py:289` `"manifest = load_manifest(str(_SHIPPED_MANIFEST), env={})"`
loads the shipped manifest with `env={}` and every reference resolves to empty
without complaint. The real risk direction is therefore a false GREEN, not a
false red.

### 8.4 Static readiness: `make doctor`

`make doctor` runs `boltrig doctor --env-file .env --manifest manifest.yaml`
([`Makefile:478`](../../../Makefile) `"$(PY) -m boltrig.api.cli doctor --env-file .env --manifest manifest.yaml $(ARGS)"`),
`ARGS="--production"` for deploy-blocking posture. Check order:
datastores, auth, edge, manifest, retired runtimes, stack-tool state, model
posture, memory posture, Codex release admission, backup, durable engine
([`boltrig/api/doctor.py:110`](../../../boltrig/api/doctor.py) `"_check_datastores(e, prod, checks)"`).
A missing manifest is a production FAIL and a development WARN; a manifest that
fails to load is always a FAIL and every manifest-dependent check is then
skipped.

`make doctor-fixture` proves the secure production fixture has no failures, and
it is a prerequisite of the `quality` aggregate.

### 8.5 Release

1. Set the protected environment's `BOLTRIG_RELEASE_MODE` repository variable to
   exactly `core` or `full`. The preflight job validates it with
   `scripts/validate_release_mode.py` before ten minutes of builds.
2. `make compose-validate` renders the merged release model twice (base and
   secure) with `BOLTRIG_RELEASE_MODE=core` and pipes it through
   `scripts/validate_release_compose.py`, which requires digest-pinned images,
   no build definitions, an identical release-mode binding on four services, and
   the browser executor isolated on `browser-egress`.
3. `make release-validate` verifies every digest, then runs tool probes and the
   PRODUCTION doctor inside an ephemeral image made only from the signed kernel
   and fleet images, against `RELEASE_ENV` and `RELEASE_MANIFEST`.
4. `make release-up` pulls and starts with `--no-build`.

### 8.6 Diagnosing a configuration problem

- "Which manifest did this process load?" The boot log line
  `booted from manifest %s (tenant %s)`
  ([`boltrig/api/bootstrap.py:453`](../../../boltrig/api/bootstrap.py) `"booted from manifest %s (tenant %s)"`),
  or `no manifest found; booted minimal demo tenant 'default'`.
- "Do my processes agree?" Read the birth-profile projection and compare
  `manifest_generation` across process kinds (5.4). A mismatch is reported, not
  enforced.
- "Is a knob real?" `make unwired-claims` runs
  `scripts/check_unwired_claims.py`, whose PART 3 flags every boolean key in
  `manifest.example.yaml` that no Python source names at all
  ([`scripts/check_unwired_claims.py:304`](../../../scripts/check_unwired_claims.py) `"def unread_manifest_keys(manifest_text: str, sources: dict)"`).
  It matches a BARE name against the whole source blob, so it catches an
  entirely unread key and nothing subtler; and it reads only `key: true|false`
  lines, so a commented-out block or a non-boolean key is invisible to it.
  Live waiver: `incremental`, owner `memory-maintainers`, expiring 2026-09-30
  ([`docs/refactoring/unwired-claims-allow.json`](../../../docs/refactoring/unwired-claims-allow.json) `"SURFACED IN THE UI, so an operator can toggle it and it does nothing"`).
- "Is the public template clean?" `make public-product-validate` refuses
  personal markers, a non-Bifrost standard route, a bundled model identity, any
  non-empty `*API_KEY`/`*ACCESS_TOKEN` assignment and a non-empty
  `TEAMS_WEBHOOK`
  ([`scripts/validate_public_product.py:114`](../../../scripts/validate_public_product.py) `".env.example contains a non-empty provider secret assignment"`).

---

## 9. Failure modes and fail-open/fail-closed posture

### 9.1 The environment classification asymmetry

`production_signal()` returns the FIRST explicit production signal:
`BOLTRIG_PRODUCTION` truthy, or `ENV`/`BOLTRIG_ENV`/`APP_ENV` in
`{prod, production, staging}`
([`boltrig/config/environment.py:8`](../../../boltrig/config/environment.py) `_PRODUCTION_VALUES = frozenset({"prod", "production", "staging"})`).
`development_signal()` requires an AFFIRMATIVE `{dev, development, local, test}`
([`boltrig/config/environment.py:46`](../../../boltrig/config/environment.py) `for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):`).
The second function exists because a control whose permissive branch was "no
production signal" permitted on every environment nobody had configured, and a
real client on a public domain returned no production signal
([`boltrig/config/environment.py:36`](../../../boltrig/config/environment.py) `"permissive branch is the absence of a signal is not a gate"`).
Nothing in the shipped Compose or `.env.example` sets any of the four, so the
default posture of a stock deployment is NEITHER production nor development.

| guard | posture | proof |
| --- | --- | --- |
| dev auth under a production signal | fail-closed, FATAL | [`boltrig/api/boot_guards.py:33`](../../../boltrig/api/boot_guards.py) `"FATAL: BOLTRIG_DEV_AUTH is set with a production signal"` |
| placeholder audit key under a production signal | fail-closed, FATAL; WARN otherwise | [`boltrig/api/boot_guards.py:58`](../../../boltrig/api/boot_guards.py) `"if signal is not None and is_placeholder_secret(key):"` |
| default seal key under a production signal | fail-closed, FATAL; dev key otherwise | [`boltrig/store/sealing.py:173`](../../../boltrig/store/sealing.py) `"if signal is not None and (not key or key == _DEV_SEAL_KEY):"` |
| no auth configured | fail-closed, every request 401 | [`boltrig/api/bootstrap.py:496`](../../../boltrig/api/bootstrap.py) `raise HTTPException(status_code=401, detail="authentication is not configured")` |
| partial manifest OIDC trio | fail-closed, refuses composition | [`boltrig/api/auth_selection.py:71`](../../../boltrig/api/auth_selection.py) `"manifest identity OIDC trust is partial"` |
| manifest OIDC trio differs from process trio | fail-closed, refuses composition | [`boltrig/api/auth_selection.py:75`](../../../boltrig/api/auth_selection.py) `"manifest identity OIDC trust differs from process OIDC trust"` |
| `identity.provider: saml` | fail-closed at LOAD | [`boltrig/config/manifest.py:505`](../../../boltrig/config/manifest.py) `"identity.provider 'saml' is not implemented"` |
| sensitive endpoint changed during composition | fail-closed, `RuntimeError` | [`boltrig/api/bootstrap.py:440`](../../../boltrig/api/bootstrap.py) `"sensitive model routing changed during process composition"` |
| mass capability deactivation | fail-closed, aborts before any write | [`boltrig/config/manifest_reconcile.py:132`](../../../boltrig/config/manifest_reconcile.py) `"raise BulkCapabilityDeactivationError("` |
| `chat.default_capability` / `skills_by_role` absent | fail-closed (empty) | [`boltrig/config/manifest.py:312`](../../../boltrig/config/manifest.py) `"code defaults stay empty and a manifest-less boot is fail-closed"` |
| `development_posture` malformed date or `covers` | fail-closed to full four-eyes | [`boltrig/config/manifest.py:682`](../../../boltrig/config/manifest.py) `"must be full four-eyes, never an unbounded or"` |
| dev egress loopback conditions | fail-closed, returns a REASON not a bool | [`boltrig/config/dev_egress.py:133`](../../../boltrig/config/dev_egress.py) `"if posture is None or not posture.enabled:"` |
| `BOLTRIG_ADDONS` naming an unregistered addon | fail-closed, RAISES at import | [`boltrig/addons/__init__.py:167`](../../../boltrig/addons/__init__.py) `"names unregistered addon(s)"` |
| release mode absent or decorated | fail-closed at the gate: `invalid_release_mode` | [`boltrig/api/codex_readiness.py:42`](../../../boltrig/api/codex_readiness.py) `return "invalid", None` |

Deliberate FAIL-OPEN branches, each with a stated reason:

| branch | direction | reason given |
| --- | --- | --- |
| a manifest adapter whose `module_ref` will not import | fail-open, warn and continue boot | one stale ref must not make the kernel unbootable ([`boltrig/config/manifest_apply.py:125`](../../../boltrig/config/manifest_apply.py) `"One stale module_ref must not take down the whole boot"`) |
| a malformed model price | fail-open, entry dropped, tier fallback | a bad price must never block boot, and a silent zero would bypass the budget gate |
| a bad skill file at boot | fail-open, warn | [`boltrig/api/bootstrap.py:312`](../../../boltrig/api/bootstrap.py) `"except Exception as exc:  # a bad skill file should not stop boot"` |
| `build_diversion_resolver` on a malformed declaration | fail-open to DISABLED (which is the safe direction here) | a stack must not refuse to boot over a development convenience |
| `browser_automation_wanted` on an unreadable manifest | answers False | posture is logged; the detail is withheld because a loader error can quote `${ENV}` values |
| the API chat factory's manifest re-read | fail-open to the empty `ChatConfig` | no stated reason; the `except Exception: pass` is bare ([`boltrig/api/bootstrap.py:591`](../../../boltrig/api/bootstrap.py) `"except Exception:"`) |

### 9.2 What happens with no manifest at all

`build_kernel_async` constructs a `Kernel` with NO `blocking_verbs`, NO
`approval_timeout_seconds` and NO `development_posture`, then seeds a minimal
demo tenant called `default`
([`boltrig/api/bootstrap.py:459`](../../../boltrig/api/bootstrap.py) `"no manifest found; booted minimal demo tenant '%s'"`).
That is a legitimate development state and it is loud in the log, but it means a
mis-set `BOLTRIG_MANIFEST` produces a running, healthy stack with an empty
always-block list rather than a boot failure.

---

## 10. What is proven

| invariant | what it binds here | representative test |
| --- | --- | --- |
| `CODEX-COMPOSITION-1` | one snapshot per serving process; the kernel does not re-read; the same snapshot seeds auth and kernel policy; gateway export precedes model composition | `tests/unit/test_codex_trusted_composition.py::test_kernel_uses_the_composition_manifest_snapshot_without_rereading`; `tests/unit/test_model_runtime_composition.py::test_manifest_gateway_is_exported_before_process_model_resources_are_composed` |
| `SEC-171` | scoped-declarative capability reconciliation and the mass-deactivation guard | `tests/integration/test_manifest_reconciliation.py::test_empty_manifest_aborts_without_confirm_and_succeeds_with_it` |
| `SEC-68` | a manifest advertising `identity.provider: saml` is rejected at load | `tests/security/test_auth.py::test_saml_provider_config_refuses_to_boot` |
| `FR-COST-04` | the per-model price table overrides the tier default; the tier vocabulary is closed across manifest and control | `tests/security/test_cost_trueup.py::test_cost_tier_vocabulary_is_closed_across_manifest_and_control` |
| `FR-EXT-01` | a project adapter declared by `module_ref` loads at boot with no core edit | `tests/integration/test_round_fifteen_bundle.py::test_project_adapter_loads_by_module_ref` |
| `FR-EXT-02` | `mcp.consume` entries register INERT pending review | `tests/integration/test_round_fifteen_bundle.py::test_consumed_mcp_servers_register_inert_pending_review` |
| `FR-RUN-01` | doctor reports a manifest still enabling a retired runtime | `tests/unit/test_doctor.py::test_doctor_reports_a_manifest_still_enabling_the_retired_pi_runtime` |
| `FR-HOST-13` | the manifest exports browser cloud policy without secret material and does not override an explicit env value | `tests/integration/test_round_two_manifest.py::test_manifest_export_does_not_override_browser_cloud_policy` |
| `FR-ADM-02` | Admin config round-trips to a manifest and supports rollback | `tests/integration/test_round_three_studios.py::test_admin_config_round_trips` |
| `IAC-005` | release mode is an exact protected-environment decision; core omits only desktop assets and records disabled admissions | `tests/deploy/test_release_can_actually_publish.py::test_release_mode_accepts_only_the_two_exact_postures` |
| `SEC-137` | the release Compose overlay pins digests and both fleet entry points | `tests/deploy/test_release_images.py::test_release_compose_validator_rejects_builds_tags_and_source_mounts` |
| `SEC-WRK-30` | per-boot startup receipts from the exact effective manifest, compared only against the latest API reference | `tests/security/test_birth_profile_receipts.py::test_projection_compares_every_instance_to_a_reference_without_claiming_parity` |
| `SEC-14` | the manifest's `hitl.approval_timeout_seconds` is threaded manifest to Kernel to HITLManager and never read ad hoc | `tests/security/test_hitl_timeout.py` |
| (unbound) | the shipped example parses with the shipping loader | `tests/unit/test_config_validate_cli.py::test_the_shipped_example_parses_with_the_shipping_loader` |
| (unbound) | the 24h approval-window floor holds at both shipped sites | `tests/security/test_operator_seat_boundary.py::test_shipped_approval_timeout_meets_the_24h_floor_at_both_sites` |
| (unbound) | no default lane in either the template or the local active manifest targets a retired runtime | `tests/integration/test_round_two_manifest.py::test_no_default_lane_targets_a_retired_runtime` |

---

## 11. RISKS

RISK-1: **The `dev_egress_loopback` manifest key can never be read.**
`build_diversion_resolver` asks for `manifest.section("dev_egress_loopback")`
([`boltrig/kernel/dev_egress_runtime.py:84`](../../../boltrig/kernel/dev_egress_runtime.py) `section = manifest.section("dev_egress_loopback")`),
but `FleetManifest.extra` is built from a closed fourteen-name tuple that does
not contain it
([`boltrig/config/manifest.py:862`](../../../boltrig/config/manifest.py) `"extra={k: doc[k] for k in ("`),
so `section()` returns `{}` for every real manifest and the resolver is
permanently `DiversionResolver(None)`. The whole court-permitted feature is
unreachable from a manifest. Its tests never notice because they hand
`build_diversion_resolver` a stub whose `section()` answers any name
([`tests/security/test_dev_egress_loopback.py:178`](../../../tests/security/test_dev_egress_loopback.py) `"def section(self, _name):"`),
and the unwired-claims gate cannot see it because the block is commented out in
the template. Bounded: `extra` is assigned in exactly one place
(`rg -n "extra={" boltrig/config/manifest.py`), `effective_manifest_from_desired`
uses `dataclasses.replace` and preserves it, and every other `.section()` caller
names a key that IS in the tuple (`rg -n "\.section\(" --glob '!tests/**'`),
2026-08-24, pinned tree.

RISK-2: **The API serving process holds three manifest reads, not one.**
`CODEX-COMPOSITION-1` says "at most one manifest snapshot"; the API composes one
at import, re-reads the file in `chat_factory` at lifespan startup
([`boltrig/api/bootstrap.py:590`](../../../boltrig/api/bootstrap.py) `"chat_cfg = load_manifest(manifest_path).chat"`)
and opens it a third time, uninterpolated, for `AdminConfig`
([`boltrig/api/platform_bootstrap.py:110`](../../../boltrig/api/platform_bootstrap.py) `"admin = AdminConfig(kernel.store, tenant_id=tenant, path=manifest_path)"`).
A file changed between import and lifespan therefore splits the API's kernel
policy from the API's chat policy, and the birth-profile digest cannot detect it
because only the composition snapshot enters `manifest_generation`. The
invariant's own test monkeypatches `_build_chat_wiring` away, so this path is
never exercised
([`tests/unit/test_codex_trusted_composition.py:278`](../../../tests/unit/test_codex_trusted_composition.py) `"_build_chat_wiring"`).

RISK-3: **The shipped example manifest carries the exact approval window a court
found harmful.** `hitl.approval_timeout_seconds: 3600`
([`manifest.example.yaml:325`](../../../manifest.example.yaml) `"approval_timeout_seconds: 3600"`),
while the code's floor is 86400 and its comment records that one hour "is the
actual proximate cause of what was experienced as deadlock"
([`boltrig/config/manifest.py:204`](../../../boltrig/config/manifest.py) `"is the actual proximate cause of what was"`).
A stated value is honoured unclamped by design, and `genesis.sh` copies this file
to `manifest.yaml` verbatim, so every genesis-provisioned tenant starts on the
one-hour window unless someone edits it.

RISK-4: **`genesis.sh` mints the audit key but not the seal key.** It calls
`gen_secret` for `POSTGRES_PASSWORD` and `BOLTRIG_AUDIT_HMAC_KEY` and
`gen_ed25519_seed` for the device lease key
([`genesis.sh:104`](../../../genesis.sh) `"gen_secret BOLTRIG_AUDIT_HMAC_KEY"`),
and never touches `BOLTRIG_SEAL_KEY` (bounded: `grep -n "SEAL_KEY" genesis.sh`
returns nothing, 2026-08-24). Genesis also sets no production signal, so
`_active_fernets` takes the fall-back branch and every `credential_refs` row is
sealed with the in-source `dev-insecure-seal-key`, which is plaintext-equivalent
at rest to anyone with this repository.

RISK-5: **The stock template boots a model endpoint with an empty model name.**
`model: ${BOLTRIG_DEFAULT_MODEL:-}`
([`manifest.example.yaml:69`](../../../manifest.example.yaml) `"model: ${BOLTRIG_DEFAULT_MODEL:-}"`)
and `BOLTRIG_DEFAULT_MODEL` appears nowhere in `.env.example`. `ModelEndpoint`
does not validate `model` for emptiness, and `_check_model_posture` counts
endpoints and checks the sensitive route but never checks that an endpoint names
a model (bounded: `grep -n "\.model\b" boltrig/api/doctor.py` returns nothing,
2026-08-24). The intent is deliberate (bring your own Bifrost) but the failure
surfaces only at the first model call.

RISK-6: **The manifest comment that `credential_ref` "is never
`${ENV}`-interpolated" is not a property of the loader.** `_interpolate` walks
the WHOLE document before any parsing
([`boltrig/config/manifest.py:442`](../../../boltrig/config/manifest.py) `"def _interpolate(obj: Any, env: Mapping[str, str]) -> Any:"`),
so `credential_ref: ${LINEAR_MCP_TOKEN}` is substituted with the token VALUE and
that value is then written into `credential_refs` as the lookup key
([`boltrig/config/control_mcp.py:79`](../../../boltrig/config/control_mcp.py) `"ref=ref,"`).
`bind_mcp_credential` refuses only the legacy `token` and `credential` keys and
cannot detect plaintext arriving through `credential_ref`
([`boltrig/config/control_mcp.py:70`](../../../boltrig/config/control_mcp.py) `"passes raw secret material; use 'credential_ref'"`).
The same shape applies to `adapters[].credential.ref`.

RISK-7: **`config-validate` documents a false-red it cannot produce.** The
module's own contract promises a failure on an unset `${VAR}` naming the variable
([`boltrig/api/config_validate.py:33`](../../../boltrig/api/config_validate.py) `"That failure direction is safe (a"`);
`_interpolate` substitutes the empty string and never raises. An operator who
follows that paragraph will believe a bare run proves more than it does.

RISK-8: **Routine chat inside the API gets no manifest chat policy.**
`register_boltrig_tasks` builds a second `ChatService` with `chat_config`
omitted
([`boltrig/fleet/hatchet_app.py:241`](../../../boltrig/fleet/hatchet_app.py) `"routine_chat = _routine_chat_service(kernel, spawner) if spawner is not None else None"`),
and `ChatService` then uses a bare `ChatConfig()`
([`boltrig/fleet/chat.py:91`](../../../boltrig/fleet/chat.py) `"self._cfg = chat_config if chat_config is not None else ChatConfig()"`),
i.e. the code-default MAXIMUM caps. A manifest that TIGHTENS an attachment or
pagination cap is therefore not honoured on the workflow-driven routine path in
the API process, while the Hatchet worker's equivalent does thread
`manifest.chat`.

RISK-9: **Thirty-seven `BOLTRIG_*` variables that shipped code reads are
documented nowhere in the operator-facing files** (7.1). Three of them
(`BOLTRIG_AUTH_MODE`, `BOLTRIG_SESSION_TENANT`, `BOLTRIG_SESSION_COOKIE_SECURE`)
are the entire first-party login posture, and one (`BOLTRIG_MANIFEST`) silently
changes which tenant the whole stack serves.

RISK-10: **`manifest.example.yaml` is a live boot fallback outside a container.**
It is the last candidate in `_MANIFEST_CANDIDATES`
([`boltrig/api/bootstrap.py:52`](../../../boltrig/api/bootstrap.py) `"manifest.example.yaml",`),
so a source-tree run with no `manifest.yaml` boots the template tenant
(`tenant_id: ${BOLTRIG_TENANT_ID:-default}`) complete with its 3600-second
approval window, rather than the loud `no manifest found` demo path. Inside the
shipped images the file is absent, so the exposure is developer boxes and any
non-Compose source deployment.

RISK-11: **The unwired-claims manifest gate is a bare-name substring match over
one boolean form.** `unread_manifest_keys` matches `\bkey\b` against the
concatenation of every Python source
([`scripts/check_unwired_claims.py:313`](../../../scripts/check_unwired_claims.py) `"if not re.search(rf"`),
so a knob named `enabled`, `panel` or `continuity` passes on any unrelated
occurrence anywhere in the tree, and only `key: true|false` lines are considered
at all. It proves the absence of a name, not the presence of a reader.

RISK-12: **`_HMAC_KEY` is bound at module import.**
([`boltrig/kernel/audit.py:28`](../../../boltrig/kernel/audit.py) `_HMAC_KEY = os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()`)
Any environment mutation after `boltrig.kernel.audit` is imported, including one
by a test fixture or a future `export_runtime_environment` extension, is not
observed by the audit chain while `refuse_default_audit_key_in_prod` reads the
LIVE environment. The two can disagree.

---

## 12. OPEN QUESTIONS

Q1. Was the omission of `dev_egress_loopback` from the `extra` allow-list
(RISK-1) a regression or has the feature never been reachable from a manifest?
`git log -S 'dev_egress_loopback' -- boltrig/config/manifest.py` on the full
history would settle it; this reading is pinned to one commit and did not walk
history.

Q2. Does the API's routine `ChatService` (RISK-8) ever carry attachments or
paginate a conversation? If it cannot, the divergent caps are inert rather than
a policy hole. Settling it needs the chat and workflow areas: trace
`run_workflow_body(..., routine_chat=...)` to every `ChatService` method it
reaches.

Q3. `mastra` is retained in `extra` but no reader was found (bounded:
`rg -n 'section\("mastra"\)|\bmastra\b' boltrig/`, 2026-08-24, returns only the
allow-list tuple). Is the section retained for a future adapter bind, or is it
residue? Its manifest block says "inert until adapters bind", which is
consistent with either.

Q4. `evaluation`, `notifications` and `personal_agents` are in the `extra`
allow-list and present in the template, but no `.section()` call names them
(bounded: the `rg -n "\.section\("` sweep in section 5). They are presumably read
by their own subsystems through a different accessor. Confirming which requires
the eval, notification and personal-agent areas.

Q5. What is the intended behaviour when `BOLTRIG_MANIFEST` names a path that
does not exist? Today `_find` skips it silently and falls through to
`/app/manifest.yaml`, `manifest.yaml` and then the example. Whether an explicit
but missing `BOLTRIG_MANIFEST` should be a hard failure is a product decision,
not a code reading.

Q6. Under Compose, a missing host `manifest.yaml` makes Docker create a
DIRECTORY at `/app/manifest.yaml`. `os.path.exists` answers True for a directory,
so `_find_manifest` would select it and `open()` would raise `IsADirectoryError`
out of composition. This was reasoned from the code and Docker's documented
bind-mount behaviour and was NOT observed; running a container would settle it,
and the contract forbids that here.

Q7. Is any deployed tenant's `manifest.yaml` still carrying
`approval_timeout_seconds: 3600` inherited from the template (RISK-3)? Only an
inspection of the live stacks would answer it, and no deployed environment was
read.

---

## 13. Requirements

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1100 | `load_manifest` parses YAML, interpolates `${ENV}` references, then builds frozen dataclasses. | IMPLEMENTED | `boltrig/config/manifest.py:825` "def load_manifest(path: str, *, env:" ; tests/unit/test_config_validate_cli.py::test_the_shipped_example_parses_with_the_shipping_loader | CODEX-COMPOSITION-1 |
| BT-REQ-1101 | An unset `${VAR}` with no default interpolates to the empty string and never raises. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:452` "return env.get(name, default if default is not None else "")" ; no test asserts it, though tests/unit/test_readiness.py:289 loads the shipped manifest with env={} | - |
| BT-REQ-1102 | The `${VAR:?message}` form is not recognised and remains a literal string in the document. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:438` "_VAR = re.compile(r" ; searched tests/ for `:?` manifest cases, none found | - |
| BT-REQ-1103 | `tenant_id` is the only mandatory top-level manifest key; its absence raises `KeyError`. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:836` "tenant_id = str(doc["tenant_id"])" ; no test found for the missing-key case | - |
| BT-REQ-1104 | A manifest declaring both `agents` and `hierarchy` is rejected at load. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:838` "manifest must declare agents or legacy hierarchy, not both" ; no test found | - |
| BT-REQ-1105 | A manifest advertising `identity.provider: saml` is rejected at load rather than falling back to env-selected auth. | IMPLEMENTED | `boltrig/config/manifest.py:505` "identity.provider 'saml' is not implemented" ; tests/security/test_auth.py::test_saml_provider_config_refuses_to_boot | SEC-68 |
| BT-REQ-1106 | The `agents` section is a closed key set and must declare at least one named agent. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest_agents.py:34` "agents.named must declare at least one named agent" ; no direct test found in tests/ | - |
| BT-REQ-1107 | Each named agent's address and scope_id must match a lowercase slug, its runtime must be codex, script or python-script, its skills 1..64 bounded strings, and its depth 1..5. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest_agents.py:57` "if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,62}", address):" ; no direct test found | - |
| BT-REQ-1108 | Named-agent names and addresses are unique and `agents.default` must name a declared address. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:165` "named agent names and addresses must be unique" ; no direct test found | - |
| BT-REQ-1109 | A legacy `hierarchy` manifest is normalised to the flat roster, the chief taking the address `cos`. | IMPLEMENTED | `boltrig/config/manifest_agents.py:107` "address="cos"," ; tests/integration/test_round_two_manifest.py::test_no_default_lane_targets_a_retired_runtime | FR-RUN-01 |
| BT-REQ-1110 | `spawn_rules` is a closed schema bounded to 128 unique rules, priority 0..1000, depth 1..10, with `name`, `priority`, `match` and `capability` required. | IMPLEMENTED | `boltrig/config/spawn_rules.py:184` "is missing required fields: " ; tests/unit/test_config_validate_cli.py::test_the_exact_prod_crash_is_a_preflight_failure_now | - |
| BT-REQ-1111 | The cost-tier vocabulary is closed to cheap, standard and expensive across manifest and control. | IMPLEMENTED | `boltrig/config/manifest.py:625` "cost_tier=validate_cost_tier(str(raw.get("cost_tier", "standard")))" ; tests/security/test_cost_trueup.py::test_cost_tier_vocabulary_is_closed_across_manifest_and_control | FR-COST-04 |
| BT-REQ-1112 | The budget window vocabulary is closed to run, daily and monthly. | IMPLEMENTED | `boltrig/config/manifest.py:99` "budget window must be run, daily, or monthly" ; tests/integration/test_round_two_manifest.py::test_manifest_budget_window_vocabulary_is_closed | - |
| BT-REQ-1113 | A model price is a float or an input/output pair in micros per token; a negative or unparseable rate is dropped so the model falls back to its cost tier rather than billing zero. | IMPLEMENTED | `boltrig/config/manifest.py:542` "return parsed if parsed >= 0 else None" ; tests/security/test_cost_trueup.py::test_model_price_from_config_overrides_tier_default | FR-COST-04 |
| BT-REQ-1114 | The default approval window is 86400 seconds at both the dataclass and the parser fallback, and a stated window is honoured unclamped. | IMPLEMENTED | `boltrig/config/manifest.py:213` "APPROVAL_TIMEOUT_SECONDS_FLOOR = 86400" ; tests/security/test_operator_seat_boundary.py::test_shipped_approval_timeout_meets_the_24h_floor_at_both_sites | - |
| BT-REQ-1115 | Nine chat ceilings are tighten-only: a manifest value is clamped into [0, code default] and a malformed value keeps the default. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:754` "return min(default, max(0, value))" ; no test found under tests/ naming `_tighten_cap` | - |
| BT-REQ-1116 | `chat.heartbeat_seconds` is honoured as supplied and is not tighten-only; a value at or below zero disables the heartbeat. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:813` "def _parse_heartbeat(raw_value: Any) -> float:" ; no test found | - |
| BT-REQ-1117 | `FleetManifest.extra` retains exactly fourteen named raw sections. | IMPLEMENTED | `boltrig/config/manifest.py:862` "extra={k: doc[k] for k in (" ; tests/integration/test_round_two_manifest.py::test_manifest_preserves_boltrig_v2_stack_sections | - |
| BT-REQ-1118 | `FleetManifest.section(name)` returns an empty dict for any key outside the retained set. | IMPLEMENTED | `boltrig/config/manifest.py:397` "return dict(value) if isinstance(value, dict) else {}" ; tests/security/test_dev_egress_loopback.py exercises the accessor through a stub | - |
| BT-REQ-1119 | `development_posture` is parsed from the manifest root and a malformed `expires_at` or `covers` yields None and (), which the posture gate refuses. | IMPLEMENTED | `boltrig/config/manifest.py:676` "def _parse_development_posture(raw: Mapping[str, Any])" ; tests/security cover posture_block refusals via dev_posture | - |
| BT-REQ-1120 | `apply_manifest` installs the manifest's network posture as the process-wide egress default before any adapter is constructed. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest_apply.py:221` "set_default_network_config(network.as_egress_config())" ; no test found asserting the ordering | - |
| BT-REQ-1121 | Manifest discovery tries `BOLTRIG_MANIFEST`, `/app/manifest.yaml`, `manifest.yaml`, then `manifest.example.yaml`, reading the environment variable live. | IMPLEMENTED | `boltrig/api/bootstrap.py:49` "_MANIFEST_CANDIDATES = (" ; tests/integration/test_manifest_boot.py sets BOLTRIG_MANIFEST and boots | - |
| BT-REQ-1122 | `manifest.yaml` is gitignored, absent from the referent, and not baked into the kernel or fleet images. | IMPLEMENTED | `.gitignore:5` "manifest.yaml" ; bounded grep of deploy/ for manifest.example, 2026-08-24 | - |
| BT-REQ-1123 | Compose bind-mounts the operator's `manifest.yaml` read-only at `/app/manifest.yaml`. | IMPLEMENTED | `docker-compose.yml:174` "./manifest.yaml:/app/manifest.yaml:ro" | - |
| BT-REQ-1124 | `compose_process_model_runtime` loads one snapshot and exports its gateway policy before the Codex provider and model catalogue are built. | IMPLEMENTED | `boltrig/api/model_runtime_composition.py:29` "export_runtime_environment(manifest)" ; tests/unit/test_model_runtime_composition.py::test_manifest_gateway_is_exported_before_process_model_resources_are_composed | CODEX-COMPOSITION-1 |
| BT-REQ-1125 | `build_kernel_async` uses an injected manifest snapshot verbatim and never re-reads the file. | IMPLEMENTED | `boltrig/api/bootstrap.py:429` "if manifest_snapshot is _MANIFEST_UNSET:" ; tests/unit/test_codex_trusted_composition.py::test_kernel_uses_the_composition_manifest_snapshot_without_rereading | CODEX-COMPOSITION-1 |
| BT-REQ-1126 | Composition aborts when a caller-supplied sensitive endpoint disagrees with the snapshot's. | IMPLEMENTED-UNTESTED | `boltrig/api/bootstrap.py:440` "sensitive model routing changed during process composition" ; no test found naming that message | CODEX-COMPOSITION-1 |
| BT-REQ-1127 | The API threads one composition snapshot into the kernel factory, spawner factory, principal resolver, platform factory and birth receipt. | IMPLEMENTED | `boltrig/api/app_composition.py:124` "principal_resolver=select_principal_resolver(manifest)," ; tests/unit/test_codex_trusted_composition.py::test_api_composition_shares_one_codex_config_with_every_factory | CODEX-COMPOSITION-1 |
| BT-REQ-1128 | The standalone fleet worker holds exactly one manifest snapshot for its kernel, spawner and pump. | IMPLEMENTED | `boltrig/api/worker.py:365` "manifest_path, manifest_snapshot, codex_config, model_catalogue = (" ; tests/unit/test_codex_trusted_composition.py::test_standalone_worker_shares_one_codex_provider_with_its_spawner | CODEX-COMPOSITION-1 |
| BT-REQ-1129 | The Hatchet worker holds one manifest snapshot and builds its routine chat service from that snapshot's chat config. | IMPLEMENTED | `boltrig/fleet/hatchet_bootstrap.py:92` "chat_config=manifest.chat if manifest is not None else None," ; tests/unit/test_codex_trusted_composition.py::test_default_hatchet_bootstrap_shares_one_codex_provider_with_its_spawner | CODEX-COMPOSITION-1 |
| BT-REQ-1130 | The API chat factory re-reads the manifest file at lifespan startup and swallows every exception, yielding the fail-closed empty chat config. | IMPLEMENTED-UNTESTED | `boltrig/api/bootstrap.py:590` "chat_cfg = load_manifest(manifest_path).chat" ; the invariant test monkeypatches `_build_chat_wiring` away | CODEX-COMPOSITION-1 |
| BT-REQ-1131 | `AdminConfig` opens the manifest file a third time in the API process and does not interpolate `${ENV}`, so its export carries placeholders rather than values. | IMPLEMENTED | `boltrig/config/admin.py:30` "with open(path, encoding="utf-8") as fh:" ; tests/integration/test_round_three_studios.py::test_admin_config_round_trips | FR-ADM-02 |
| BT-REQ-1132 | `register_boltrig_tasks` constructs its routine chat service without a manifest chat config, so it uses the code-default maximum caps. | IMPLEMENTED-UNTESTED | `boltrig/fleet/hatchet_app.py:241` "routine_chat = _routine_chat_service(kernel, spawner) if spawner is not None else None" ; no test found asserting its config | - |
| BT-REQ-1133 | Every serving process publishes a per-boot receipt carrying an opaque digest of its effective typed manifest. | IMPLEMENTED | `boltrig/config/birth_profile.py:71` "def manifest_generation(manifest: Any) -> str:" ; tests/security/test_birth_profile_receipts.py::test_receipt_contract_rejects_unbounded_or_incoherent_evidence | SEC-WRK-30 |
| BT-REQ-1134 | The birth-profile projection compares every instance against the latest API receipt and reports a manifest-generation mismatch without refusing service. | IMPLEMENTED | `boltrig/config/birth_profile_projection.py:45` `evidence_state = "mismatched_startup_liveness_unknown"` ; tests/security/test_birth_profile_receipts.py::test_projection_compares_every_instance_to_a_reference_without_claiming_parity | SEC-WRK-30 |
| BT-REQ-1135 | `apply_manifest` exports runtime env, installs egress defaults, plans reconciliation, seeds the projection, then reconciles, in that order. | IMPLEMENTED | `boltrig/config/manifest_apply.py:224` "plan = await plan_capability_reconciliation(" ; tests/integration/test_manifest_reconciliation.py | SEC-171 |
| BT-REQ-1136 | Capability reconciliation is declarative over `source='manifest'` rows and additive over control-plane grants, scoped org-wide. | IMPLEMENTED | `boltrig/config/manifest_reconcile.py:122` "active_manifest = [c for c in active if c.source == MANIFEST_SOURCE]" ; tests/integration/test_manifest_reconciliation.py::test_control_plane_capability_survives_a_manifest_that_omits_it | SEC-171 |
| BT-REQ-1137 | A manifest declaring no capabilities, or dropping more than max(3, half) of the active manifest-sourced set, aborts the whole apply before any write unless explicitly confirmed. | IMPLEMENTED | `boltrig/config/manifest_reconcile.py:127` "over_threshold = dropped > max(_MIN_ABSOLUTE_DROP, a_before // 2)" ; tests/integration/test_manifest_reconciliation.py::test_over_threshold_drop_aborts_without_confirm_and_succeeds_with_it | SEC-171 |
| BT-REQ-1138 | A manifest adapter whose module cannot be imported is logged and skipped so boot continues. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest_apply.py:135` "except Exception as exc:  # a bad manifest adapter must not kill boot" ; no test found naming that warning | - |
| BT-REQ-1139 | Manifest adapter credentials are seeded as `{store, ref, kind}` references and bound to the adapter, never as secret material. | IMPLEMENTED | `boltrig/config/manifest.py:52` "The ``{store, ref, kind}`` dict the credential resolver expects." ; tests/integration/test_round_fifteen_bundle.py::test_project_adapter_loads_by_module_ref | FR-EXT-01 |
| BT-REQ-1140 | The tenant verb ceiling is the union of role-mapping grants, with `*` for org-admin, and always adds `agent.send` and `chat.present`. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:431` "allow.update(("agent.send", "chat.present"))" ; no test found asserting the two added verbs | - |
| BT-REQ-1141 | `export_runtime_environment` fills only environment keys that are absent, so an explicit process value always wins. | IMPLEMENTED | `boltrig/config/manifest_runtime.py:25` "if base_url and "BOLTRIG_MODEL_GATEWAY_URL" not in target:" ; tests/integration/test_round_two_manifest.py::test_manifest_export_does_not_override_browser_cloud_policy | FR-HOST-13 |
| BT-REQ-1142 | `Settings` is a frozen dataclass built from the environment by `load_settings`, with no settings framework and no singleton. | IMPLEMENTED | `boltrig/config/settings.py:102` "def load_settings(env: Mapping[str, str]" ; exercised by tests/unit/test_doctor.py through `_secure_env` | - |
| BT-REQ-1143 | Production classification accepts `BOLTRIG_PRODUCTION` or prod/production/staging on ENV, BOLTRIG_ENV or APP_ENV; development classification requires an affirmative dev/development/local/test and never infers from absence. | IMPLEMENTED | `boltrig/config/environment.py:46` "for key in ("ENV", "BOLTRIG_ENV", "APP_ENV"):" ; tests/security/test_dev_egress_loopback.py exercises both signals as parameters | - |
| BT-REQ-1144 | A placeholder audit HMAC key under a production signal is a fatal boot failure, and a warning on every boot otherwise. | IMPLEMENTED | `boltrig/api/boot_guards.py:58` "if signal is not None and is_placeholder_secret(key):" ; tests/unit/test_doctor.py::test_production_doctor_has_no_failures_for_secure_posture | - |
| BT-REQ-1145 | An unset or default credential sealing key under a production signal is a fatal failure; otherwise the in-source dev key is used. | IMPLEMENTED | `boltrig/store/sealing.py:173` "if signal is not None and (not key or key == _DEV_SEAL_KEY):" ; exercised through tests/security credential sealing suites | - |
| BT-REQ-1146 | The audit HMAC key is bound at module import, so a later environment change is not observed by the chain. | IMPLEMENTED-UNTESTED | `boltrig/kernel/audit.py:28` "_HMAC_KEY = os.environ.get("BOLTRIG_AUDIT_HMAC_KEY", "dev-insecure-audit-key").encode()" ; no test found asserting the import-time binding | - |
| BT-REQ-1147 | One predicate answers whether a value is a placeholder secret, listing every placeholder the repository has shipped plus four fragments and a 24-character floor. | IMPLEMENTED | `boltrig/config/weak_secrets.py:45` "PLACEHOLDER_FRAGMENTS = ("CHANGE_ME", "REPLACE", "example.com", "your-org")" ; tests/unit/test_doctor.py exercises it through `_weak` | - |
| BT-REQ-1148 | `boltrig doctor` fails when `DATABASE_URL` still contains a placeholder fragment, regardless of environment. | IMPLEMENTED | `boltrig/api/doctor.py:196` "DATABASE_URL still contains a placeholder." ; tests/unit/test_doctor.py::test_production_doctor_has_no_failures_for_secure_posture | - |
| BT-REQ-1149 | Auth resolver precedence is session, then Cloudflare Access, then generic OIDC, then dev auth, then a deny-all resolver. | IMPLEMENTED | `boltrig/api/auth_selection.py:104` "if settings.session_auth_configured:" ; tests/security/test_auth.py | - |
| BT-REQ-1150 | A partial manifest OIDC trio, or a manifest trio that differs from a fully configured process trio, refuses composition. | IMPLEMENTED | `boltrig/api/auth_selection.py:75` "manifest identity OIDC trust differs from process OIDC trust" ; tests/security/test_auth.py | - |
| BT-REQ-1151 | Thirty-seven `BOLTRIG_*` variables read by shipped code appear in no operator-facing configuration file. | IMPLEMENTED | bounded diff of `rg -o '\bBOLTRIG_[A-Z0-9_]+' boltrig/ services/` against `.env.example docker-compose.yml deploy/`, LC_ALL=C, 2026-08-24, pinned tree | - |
| BT-REQ-1152 | `BOLTRIG_RELEASE_MODE` admits exactly `core` or `full` with no trimming or case folding, and absence is preserved as no override. | IMPLEMENTED | `boltrig/release_mode.py:9` "VALID_RELEASE_MODES = frozenset({"core", "full"})" ; tests/deploy/test_release_can_actually_publish.py::test_release_mode_accepts_only_the_two_exact_postures | IAC-005 |
| BT-REQ-1153 | The release Compose overlay binds the release mode on kernel, fleet-worker, browser-executor and hatchet-worker, and the validator refuses a missing, decorated or disagreeing binding. | IMPLEMENTED | `scripts/validate_release_compose.py:69` "if len(set(bound_modes.values())) != 1:" ; tests/deploy/test_release_images.py::test_release_compose_validator_rejects_builds_tags_and_source_mounts | SEC-137 |
| BT-REQ-1154 | Release mode `core` disables the Codex readiness check, and `core` together with `BOLTRIG_CODEX_TRUSTED` is a hard readiness failure. | IMPLEMENTED | `boltrig/api/codex_readiness.py:43` "if mode == "core":" ; tests/unit/test_readiness.py::test_core_release_readiness_disables_codex_requested_by_the_shipped_manifest | IAC-005 |
| BT-REQ-1155 | A `full` release with no packaged-desktop origin in `BOLTRIG_CORS_ORIGINS` is a doctor failure. | IMPLEMENTED | `boltrig/api/doctor_edge.py:42` "if env.get("BOLTRIG_RELEASE_MODE") == "full" and not configured_desktop:" ; tests/unit/test_doctor.py exercises the edge checks | - |
| BT-REQ-1156 | The release workflow binds the mode, the desktop posture and the runtime admissions into an immutable `release-metadata.json` asset and refuses to change it on a re-run. | IMPLEMENTED | `.github/workflows/release.yml:289` "draft release metadata differs; refusing to change release mode or commit" ; tests/deploy/test_release_can_actually_publish.py::test_release_metadata_binds_mode_and_closed_runtime_admissions | IAC-005 |
| BT-REQ-1157 | The product name is derived from the active addon set at runtime, never from a build flag. | IMPLEMENTED-UNTESTED | `boltrig/branding.py:39` "return OPBOX_AGENTS if any(a.name == _OPBOX_ADDON for a in active) else BOLTRIG" ; searched tests/ for branding/product_name, none found | - |
| BT-REQ-1158 | `boltrig config-validate` parses a manifest with the shipping loader, exiting 0 on success, 1 on rejection with the exception type named, and 2 on a missing path. | IMPLEMENTED | `boltrig/api/config_validate.py:58` "config-validate: REFUSED - the shipping loader rejects" ; tests/unit/test_config_validate_cli.py::test_a_missing_file_is_operator_error_not_a_rejection | - |
| BT-REQ-1159 | `config-validate` cannot detect an unset `${VAR}`, because interpolation substitutes the empty string rather than failing. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:452` "return env.get(name, default if default is not None else "")" ; contradicts `boltrig/api/config_validate.py:34` "false red, never a false green" | - |
| BT-REQ-1160 | `spawn_rules` is the only manifest section whose Admin Console revision reaches runtime behaviour; every other section edit is export and history only. | IMPLEMENTED | `boltrig/config/spawn_rule_revisions.py:22` "source="process_start_manifest"," ; tests/security/test_spawn_rule_enforcement.py writes a `manifest_section` revision | - |
| BT-REQ-1161 | The `dev_egress_loopback` manifest key is unreachable: it is absent from the retained-section allow-list, so its resolver is permanently disabled. | DEAD | `boltrig/config/manifest.py:862` "extra={k: doc[k] for k in (" against `boltrig/kernel/dev_egress_runtime.py:84` "section = manifest.section("dev_egress_loopback")" ; bounded search recorded in RISK-1 | - |
| BT-REQ-1162 | The shipped example manifest declares a 3600-second approval window, one twenty-fourth of the code floor, and `genesis.sh` copies it verbatim to `manifest.yaml`. | IMPLEMENTED | `manifest.example.yaml:325` "approval_timeout_seconds: 3600" ; `genesis.sh:102` "[ -f manifest.yaml ] || cp manifest.example.yaml manifest.yaml" | - |
