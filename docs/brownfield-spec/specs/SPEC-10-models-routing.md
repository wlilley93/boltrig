---
area: 10 Model catalogue, routing, and the sensitive-to-local rule
id-block: BT-REQ-1000 .. BT-REQ-1099
referent-commit: 19bcae7fa81663fe8998377c86451ba08fb16e48
referent-branch: origin/main
author-agent: brownfield-spec agent, area 10
date: 2026-08-24
---

## Bound of this reading

Read exhaustively, top to bottom: `boltrig/fleet/model_router.py`,
`boltrig/fleet/model_gateway.py`, `boltrig/fleet/model_gateway_status.py`,
`boltrig/fleet/runtime_endpoint_policy.py`, `boltrig/fleet/codex_model_selection.py`,
`boltrig/fleet/bifrost_model_catalogue.py`, `boltrig/fleet/runtime_resolver.py`,
`boltrig/fleet/spawn_budget.py`, `boltrig/model_catalogue_policy.py`,
`boltrig/model_choice_policy.py`, `boltrig/models/model_id_policy.py`,
`boltrig/models/libraries.py`, `boltrig/config/control_model_endpoints.py`,
`boltrig/config/capability_model_routes.py`, `boltrig/config/model_profile_views.py`,
`boltrig/config/birth_profile.py`, `boltrig/identity/ai_keys.py`,
`boltrig/identity/bifrost_user_binding.py`, `boltrig/identity/bifrost_user_admin.py`,
`boltrig/identity/bifrost_user_transport.py`, `boltrig/kernel/cost.py`,
`boltrig/kernel/platform_routes/model_endpoints.py`,
`boltrig/kernel/platform_routes/chat_model_choices.py`,
`boltrig/kernel/platform_routes/bifrost_models.py`, `boltrig/kernel/call_profiles.py`,
`boltrig/store/model_endpoint_contract.py`, `boltrig/store/model_endpoints_postgres.py`,
`boltrig/store/model_endpoints_memory.py`, the `bifrost` and `local-model` services in
`docker-compose.yml`, and the `models:` block of `manifest.example.yaml`.

Read in the ranges around every call site found by `rg`: `boltrig/config/manifest.py`,
`boltrig/config/manifest_apply.py`, `boltrig/config/manifest_runtime.py`,
`boltrig/api/bootstrap.py`, `boltrig/api/worker.py`, `boltrig/api/platform_bootstrap.py`,
`boltrig/api/model_runtime_composition.py`, `boltrig/api/doctor.py`,
`boltrig/fleet/spawn.py`, `boltrig/fleet/spawn_completion.py`,
`boltrig/fleet/codex_runtime_support.py`, `boltrig/fleet/result.py`,
`boltrig/memory/adapter.py`, `boltrig/memory/adapter_writes.py`,
`boltrig/memory/cognee_model_binding.py`, `boltrig/knowledge/projections.py`,
`boltrig/distill/corpus.py`, `boltrig/distill/adapter.py`, `boltrig/store/schema.sql`,
`boltrig/store/rls.sql`, `migrations/versions/00{48,69,71}*.py`, `genesis.sh`,
`.env.example`, `Makefile`, `deploy/compose.secure.yml`, `tests/invariants.yaml`,
`tests/security/test_sensitive_routing.py`, `tests/security/test_model_endpoint_lifecycle.py`,
`tests/security/test_cost_trueup.py`, `tests/security/test_chat_model_choices.py`,
`tests/security/test_round_six.py`, `tests/unit/test_bifrost_custom_provider_base_url.py`,
`tests/unit/test_bifrost_selfhosted_key.py`, `tests/unit/test_model_catalogue_policy_declared.py`,
`tests/unit/test_user_model_id_policy.py`.

NOT read exhaustively and therefore NOT specified here: the Codex model-proxy grant
subsystem (`boltrig/fleet/domain/model_proxy_*.py`,
`boltrig/fleet/application/model_proxy_cache.py`,
`boltrig/fleet/infrastructure/postgres_model_proxy_grant*.py`) beyond its top-level
type definitions; the Codex cell/runtime egress path itself; the realtime voice call
lifecycle beyond `call_profiles.py`; the Worker UI under `apps/worker/`. Those belong
to other areas of this corpus.

The task scope named `boltrig/models/` (51 files). That directory is the domain-record
package, not the LLM registry. Only its model-adjacent members are specified here:
`libraries.py` (`ModelEndpoint`, `AgentCapability`, `COST_TIERS`, `MODEL_MODALITIES`),
`model_id_policy.py`, `errors.py` (the four typed refusals), `ai_key_proposals.py`.
`boltrig/notification_catalogue.py` was opened and is NOT model-adjacent: it is the
approval/escalation/hitl_expired/work_status notification event table
([`boltrig/notification_catalogue.py:12`](../../../boltrig/notification_catalogue.py) `"NOTIFICATION_EVENTS = ("`), so it is out of scope for this area.

---

## 2. Purpose

This subsystem decides, for one model-bearing call, WHICH endpoint the bytes may reach,
and it is the place where the estate's residency doctrine is enforced rather than
asserted. It holds the endpoint catalogue as tenant-scoped data, a classifier that
decides whether a payload is sensitive, a router that refuses any sensitive payload a
local endpoint cannot serve, an optional OpenAI-compatible gateway (Bifrost) that
standard traffic may be re-pointed through for cache and cost, and the price table that
turns reported tokens into charged micros. Nothing in it holds provider credentials: it
routes, classifies, refuses, and prices.

## 3. Boundaries

**Owns.** The `ModelEndpoint` record and its store contract; the manifest `models:`
section (`endpoints`, `default`, `sensitive_endpoint`, `prices`); the sensitive-to-local
guard; the modality guard; the conversation-to-model gateway binding; the read-only
Bifrost model catalogue; the scoped Bifrost provider/virtual-key binding; the per-model
price table and the micros arithmetic.

**Does not own.** Credential material (sealed in `credential_refs`, resolved kernel-side
by `boltrig/identity/ai_keys.py`); the Codex runtime and its model proxy; grant checking;
the HITL approval mechanism the `control.model_endpoint.*` verbs ride on; budget window
storage.

**Forbidden imports.** `kernel/` and `models/` import nothing from `fleet/`
([`AGENTS.md:41`](../../../AGENTS.md) `"Respect the import boundary"`). This
is why the router lives in `fleet/` while the price arithmetic lives in `kernel/cost.py`:
the router is a fleet-side decision, pricing is a kernel-side ledger input. The two
shared policy modules that BOTH sides need were hoisted to the package root instead of
either half: `boltrig/model_catalogue_policy.py` and `boltrig/model_choice_policy.py`
are imported by `boltrig/config/control_model_endpoints.py` (kernel-side authoring) and
`boltrig/fleet/codex_model_selection.py` (fleet-side admission) alike
([`boltrig/model_catalogue_policy.py:1`](../../../boltrig/model_catalogue_policy.py) `"Shared fail-closed policy for exact text-capable catalogue membership."`).

`ModelGateway` explicitly disclaims authority: it "has no authorization role and holds no
capability/credential logic (P1)"
([`boltrig/fleet/model_gateway.py:11`](../../../boltrig/fleet/model_gateway.py) `"This module is the read-side seam only."`).

`BifrostModelCatalogue` disclaims administration: "deliberately an inventory seam, not a
Bifrost administration client"
([`boltrig/fleet/bifrost_model_catalogue.py:3`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"an inventory seam, not a Bifrost administration client"`).

## 4. Objects and contracts

### 4.1 `ModelEndpoint` (the catalogue row)

[`boltrig/models/libraries.py:194`](../../../boltrig/models/libraries.py) `"class ModelEndpoint:"`

| field | type | default | meaning |
| --- | --- | --- | --- |
| `id` | `str` | required | tenant-scoped opaque choice id, e.g. `"anthropic-prod"`, `"local-vllm"` |
| `tenant_id` | `TenantId` | required | owning tenant; part of the primary key |
| `kind` | `str` | required | documented as `'bifrost' \| 'anthropic' \| 'openai' \| 'ollama' \| 'vllm'` ([`boltrig/models/libraries.py:197`](../../../boltrig/models/libraries.py) `"'bifrost' | 'anthropic' | 'openai' | 'ollama' | 'vllm'"`) |
| `model` | `str` | required | pinned model/version string, the key the price table uses |
| `base_url` | `str \| None` | `None` | provider address; never projected to a browser |
| `fallback` | `str \| None` | `None` | a STORED reference for a future explicit failover decision; "The router does not silently traverse it" ([`boltrig/models/libraries.py:201`](../../../boltrig/models/libraries.py) `"The router does not silently traverse it"`) |
| `data_class` | `str` | `"standard"` | `standard \| sensitive`; `sensitive` means local only ([`boltrig/models/libraries.py:204`](../../../boltrig/models/libraries.py) `"standard | sensitive (sensitive => local only)"`) |
| `is_active` | `bool` | `True` | reversible governed withdrawal |
| `modalities` | `tuple[str, ...]` | `("text",)` | what the endpoint advertises |
| `revision` | `int` | `1` | monotonic generation for approved compare-and-swap |

`__post_init__` refuses a non-positive-integer revision, lowercases and dedupes
modalities, rejects any modality outside `MODEL_MODALITIES`, and coerces an empty set
back to `("text",)`
([`boltrig/models/libraries.py:225`](../../../boltrig/models/libraries.py) `object.__setattr__(self, "modalities", values or ("text",))`).

The modality vocabulary is closed and capability-shaped, not provider-shaped:
`("text", "vision", "stt", "tts", "realtime")`
([`boltrig/models/libraries.py:32`](../../../boltrig/models/libraries.py) `MODEL_MODALITIES: tuple[str, ...] = ("text", "vision", "stt", "tts", "realtime")`).
`stt` and `tts` are separate so a transcription route can never be selected for synthesis.

### 4.2 `AgentCapability` model routes (who points at which endpoint)

[`boltrig/models/libraries.py:83`](../../../boltrig/models/libraries.py) `"class AgentCapability:"`

The generic `model_routes: dict[modality -> endpoint_id]` is authoritative; the legacy
`model_endpoint` / `vision_model_endpoint` columns remain a compatibility projection and
are folded INTO `model_routes` at construction, with the legacy value winning
([`boltrig/models/libraries.py:131`](../../../boltrig/models/libraries.py) `routes["text"] = self.model_endpoint`). `endpoint_for(modality)` is the accessor
([`boltrig/models/libraries.py:136`](../../../boltrig/models/libraries.py) `"def endpoint_for(self, modality: str)"`).

Authoring-time validation of those routes lives in
[`boltrig/config/capability_model_routes.py:17`](../../../boltrig/config/capability_model_routes.py) `"async def validated_capability_routes("`: each named endpoint must exist, be active,
and advertise the modality it is bound for; a conflicting legacy-versus-generic pair is
refused; and a capability with a single text endpoint and no vision route must name a
multimodal endpoint
([`boltrig/config/capability_model_routes.py:88`](../../../boltrig/config/capability_model_routes.py) `"a single agent model must advertise both text and vision modalities"`).

### 4.3 `ModelsConfig` (the manifest projection)

[`boltrig/config/manifest.py:69`](../../../boltrig/config/manifest.py) `"class ModelsConfig:"`

`endpoints`, `default`, `sensitive_endpoint`, `prices`. `default` is parsed and projected
but has no serving consumer today, and the platform route says so explicitly
([`boltrig/kernel/platform_routes/model_endpoints.py:79`](../../../boltrig/kernel/platform_routes/model_endpoints.py) `"serving_state": "inactive_no_consumer",`). `sensitive_endpoint` is the endpoint id
sensitive traffic is redirected to
([`boltrig/config/manifest.py:74`](../../../boltrig/config/manifest.py) `"sensitive_endpoint: str | None = None  # endpoint id for sensitive data (local)"`).

### 4.4 Identifier policies

- **Opaque choice id** (an endpoint id as seen by a caller): one bounded URL-safe path
  segment, `[A-Za-z0-9._~-]{1,160}`, never `.` or `..`, never normalised
  ([`boltrig/model_choice_policy.py:8`](../../../boltrig/model_choice_policy.py) `_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]{1,160}\Z")`).
- **Exact model id** (kernel-pinned artifacts): bounded canonical identifier, not a path,
  and refusing any segment in the mutable-alias set `{auto, beta, current, default,
  experimental, latest, preview, recommended, stable}`
  ([`boltrig/models/model_id_policy.py:8`](../../../boltrig/models/model_id_policy.py) `"_MUTABLE_MODEL_SEGMENTS = frozenset("`).
- **User model id** (a provider binding the USER connected): shape and path rules only,
  aliases allowed, on the reasoning that "on a self-hosted server EVERY tag is
  re-pointable"
  ([`boltrig/models/model_id_policy.py:50`](../../../boltrig/models/model_id_policy.py) `"on a self-hosted server EVERY tag is"`).

### 4.5 The four typed refusals

| exception | status | reason | raised when |
| --- | --- | --- | --- |
| `SensitiveDataMisrouted` | 403 | `sensitive_data_misrouted` | sensitive payload, no sensitive endpoint reachable ([`boltrig/models/errors.py:231`](../../../boltrig/models/errors.py) `"class SensitiveDataMisrouted(BoltrigError):"`) |
| `ModelEndpointUnavailable` | 409 | `model_endpoint_unavailable` | named endpoint missing, retired, wrong modality, or an unmeetable choice precondition ([`boltrig/models/errors.py:238`](../../../boltrig/models/errors.py) `"class ModelEndpointUnavailable(BoltrigError):"`) |
| `ModelCatalogueUnavailable` | 503 | `model_catalogue_unavailable` | the Bifrost catalogue could not prove a route ([`boltrig/models/errors.py:262`](../../../boltrig/models/errors.py) `"class ModelCatalogueUnavailable(BoltrigError):"`) |
| `BifrostUserBindingUnavailable` | n/a (RuntimeError) | n/a | a scoped Bifrost binding could not be proven usable ([`boltrig/identity/bifrost_user_transport.py:22`](../../../boltrig/identity/bifrost_user_transport.py) `"class BifrostUserBindingUnavailable(RuntimeError):"`) |

### 4.6 `ModelGateway` (conversation binding)

[`boltrig/fleet/model_gateway.py:33`](../../../boltrig/fleet/model_gateway.py) `"class ModelGateway:"`. An in-memory `(tenant_id, conversation_id) -> (model, expires_at)`
table, TTL-bounded and size-bounded at `_MAX_BINDINGS = 4_096`
([`boltrig/fleet/model_gateway.py:48`](../../../boltrig/fleet/model_gateway.py) `"_MAX_BINDINGS = 4_096"`). The binding unit is the CONVERSATION, not the run, because
"`run_id` is minted fresh every turn and is the wrong key"
([`boltrig/fleet/model_gateway.py:9`](../../../boltrig/fleet/model_gateway.py) `"fresh every turn and is the wrong key"`). It is affinity, never state
of record: an early eviction just re-pins next turn.

### 4.7 `BifrostModelCatalogue` (the read-only inventory)

[`boltrig/fleet/bifrost_model_catalogue.py:247`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"class BifrostModelCatalogue:"`. Returns a `BifrostCatalogueResponse`
`{status: "ok"|"unavailable", models: [{id, name, input_modalities?}], reason}` with a
closed ten-value reason vocabulary
([`boltrig/fleet/bifrost_model_catalogue.py:37`](../../../boltrig/fleet/bifrost_model_catalogue.py) `CatalogueUnavailableReason = Literal[`).

### 4.8 `BifrostUserBinding` (the scoped BYO-provider binding)

[`boltrig/identity/bifrost_user_binding.py:50`](../../../boltrig/identity/bifrost_user_binding.py) `"class BifrostUserBinding:"`. `(provider, model_id, provider_key_id, virtual_key_id,
virtual_key, credential_ref)` with `__repr__` returning `"BifrostUserBinding(redacted=True)"`.
Its `credential_ref` is derived, not chosen: `sha256(tenant \0 level \0 scope_id \0 modality)`
([`boltrig/identity/bifrost_user_binding.py:70`](../../../boltrig/identity/bifrost_user_binding.py) `"digest = hashlib.sha256("`), so the binding is idempotent per scope and modality.

## 5. Control flow

### 5.1 The main routing path (one ephemeral spawn or chat turn)

1. **Compose the process snapshot at boot.** `compose_process_model_runtime` loads the
   manifest, exports its `runtimes.gateway` block into the environment (only filling
   values that are absent), builds the trusted Codex config, and constructs ONE
   `BifrostModelCatalogue`
   ([`boltrig/api/model_runtime_composition.py:31`](../../../boltrig/api/model_runtime_composition.py) `"return manifest_path, manifest, codex_config, BifrostModelCatalogue()"`).
   *Failure branch:* no manifest means `manifest is None`, `sensitive_endpoint_id` is
   `None`, and the whole sensitive lane becomes a refusal lane (step 8).

2. **Pin the sensitive role.** `build_kernel_async` reads
   `manifest.models.sensitive_endpoint` and refuses composition if a caller-supplied id
   disagrees with the manifest
   ([`boltrig/api/bootstrap.py:437`](../../../boltrig/api/bootstrap.py) `"sensitive_endpoint_id is not None"`), raising
   `RuntimeError("sensitive model routing changed during process composition")`.

3. **Classify the payload.** `resolve_base_model` starts from the caller's
   `context.extra["data_class"] == "sensitive"` and then ORs in the deterministic PII
   scanner over the composed outbound prompt
   ([`boltrig/fleet/codex_model_selection.py:73`](../../../boltrig/fleet/codex_model_selection.py) `"sensitive = sensitive or outbound_text_classifies_sensitive(outbound_text)"`).
   The scan classifies only; it never rewrites text
   ([`boltrig/fleet/model_router.py:46`](../../../boltrig/fleet/model_router.py) `"return pii.redact(text).has_pii or pii.contains_identity(text) is not None"`).
   *Failure branch:* none. A false positive routes local, which is the safe direction.

4. **Validate any caller model choice.** A `model_endpoint_id` in `context.extra` must
   parse as an opaque choice id, else `ModelEndpointUnavailable("model choice id is
   invalid")`
   ([`boltrig/fleet/codex_model_selection.py:35`](../../../boltrig/fleet/codex_model_selection.py) `raise ModelEndpointUnavailable("model choice id is invalid")`), and a choice is
   refused outright for a non-Codex capability, a sensitive request, or a pinned profile
   ([`boltrig/fleet/codex_model_selection.py:45`](../../../boltrig/fleet/codex_model_selection.py) `capability.runtime != "codex" or sensitive or pinned_policy`).

5. **Pick the capability's endpoint for the modality.** `endpoint_id_for_modality`
   returns the explicit route, else for `vision` the vision override or the primary, else
   the primary
   ([`boltrig/fleet/model_router.py:61`](../../../boltrig/fleet/model_router.py) `"return capability.vision_model_endpoint or capability.model_endpoint"`).

6. **Resolve exactly that reference.** `_active_endpoint` does one store read and returns
   the row only when `is_active`. It deliberately does NOT traverse `fallback`: "A missing
   or retired named row is configuration failure, not permission to drop to an
   environment model or follow a stale fallback reference"
   ([`boltrig/fleet/model_router.py:149`](../../../boltrig/fleet/model_router.py) `"is configuration failure, not permission to"`).
   *Failure branch:* audit `model_endpoint_unavailable` with `endpoint_status` of
   `retired` or `missing`, then raise `ModelEndpointUnavailable`
   ([`boltrig/fleet/model_router.py:173`](../../../boltrig/fleet/model_router.py) `"raise ModelEndpointUnavailable("`).

7. **Check the modality.** If a modality was requested and the resolved row does not
   advertise it, audit `model_endpoint_modality_unavailable` and raise
   `ModelEndpointUnavailable`
   ([`boltrig/fleet/model_router.py:95`](../../../boltrig/fleet/model_router.py) `"model_endpoint_modality_unavailable",`).

8. **Apply the residency rule.** This is the load-bearing branch, in order:
   a. Not sensitive: return the resolved endpoint (possibly `None`)
      ([`boltrig/fleet/model_router.py:106`](../../../boltrig/fleet/model_router.py) `"if not sensitive:"`).
   b. Sensitive and the capability's own endpoint is `data_class == "sensitive"`: return it
      ([`boltrig/fleet/model_router.py:108`](../../../boltrig/fleet/model_router.py) `if ep is not None and ep.data_class == "sensitive":`).
   c. Sensitive and a `sensitive_endpoint_id` is configured: resolve it through the SAME
      `_active_endpoint`, and return it only if it is itself `data_class == "sensitive"`
      ([`boltrig/fleet/model_router.py:118`](../../../boltrig/fleet/model_router.py) `if local is not None and local.data_class == "sensitive":`).
   d. Otherwise: audit `sensitive_data_misrouted` carrying the attempted endpoint id and
      its data class, then raise `SensitiveDataMisrouted`
      ([`boltrig/fleet/model_router.py:134`](../../../boltrig/fleet/model_router.py) `"raise SensitiveDataMisrouted("`).
   Note the ordering consequence in (c): if `sensitive_endpoint_id` names a MISSING or
   RETIRED row, `_active_endpoint` raises `ModelEndpointUnavailable` from inside the
   sensitive branch, and that exception propagates instead of `SensitiveDataMisrouted`.
   Both are refusals; neither is a fallback.

9. **Codex/Bifrost composition, standard traffic only.** The whole Codex endpoint
   composition is gated on `not sensitive`
   ([`boltrig/fleet/runtime_resolver.py:137`](../../../boltrig/fleet/runtime_resolver.py) `if capability.runtime == "codex" and not sensitive:`). Inside it:
   a. If the caller has a non-default scoped AI key and made no explicit choice, a scoped
      Bifrost binding is minted and the endpoint becomes a synthetic
      `id="scoped-ai-default", kind="bifrost"` row pointed at the gateway
      ([`boltrig/fleet/runtime_resolver.py:224`](../../../boltrig/fleet/runtime_resolver.py) `id="scoped-ai-default",`). *Failure branch:* `BifrostUserBindingUnavailable`
      becomes `ModelEndpointUnavailable("the configured AI provider is not ready")`.
   b. Otherwise `resolve_codex_model` runs: an explicit choice must be standard,
      text-capable, exact-id, and catalogue-proven, then is rewritten to
      `kind="bifrost", base_url=gateway_url`
      ([`boltrig/fleet/codex_model_selection.py:191`](../../../boltrig/fleet/codex_model_selection.py) `return replace(selected, kind="bifrost", base_url=gateway_url)`); a pinned
      profile keeps its authored endpoint; automatic routing needs trusted Codex and a
      gateway URL and re-proves the composed `model_id` against the catalogue
      ([`boltrig/fleet/codex_model_selection.py:197`](../../../boltrig/fleet/codex_model_selection.py) `"automatic Codex routing requires the Bifrost gateway"`).

10. **Apply the conversation gateway.** `apply_conversation_gateway` re-points `base_url`
    at the gateway and pins the conversation's model. It returns the endpoint UNCHANGED
    when there is no endpoint, the data is sensitive, no gateway URL, no binding table,
    or no conversation id
    ([`boltrig/fleet/model_gateway.py:136`](../../../boltrig/fleet/model_gateway.py) `"if endpoint is None or sensitive or not gateway_url"`). An explicit user choice or
    an ordinary standard Codex turn uses `rebind` (replace affinity); anything else uses
    `bind` (first live model wins)
    ([`boltrig/fleet/runtime_endpoint_policy.py:42`](../../../boltrig/fleet/runtime_endpoint_policy.py) `"explicit_rebind=("`).

11. **Pin the pinned profile.** For a permanent process-composed profile, if the resolved
    endpoint's model is not the composed Codex model, raise
    `PinnedRuntimePolicyUnavailable`
    ([`boltrig/fleet/runtime_resolver.py:250`](../../../boltrig/fleet/runtime_resolver.py) `"the composed Codex model does not satisfy the pinned profile"`).

12. **Record what served.** The Codex profile route wins because it carries richer
    attribution; otherwise `served_model_route` projects `{model, provider}` with no
    topology and no credentials
    ([`boltrig/fleet/runtime_endpoint_policy.py:11`](../../../boltrig/fleet/runtime_endpoint_policy.py) `"Project model/provider audit truth without topology or credentials."`). An
    unavailable runtime gets no speculative model label.

### 5.2 Catalogue fetch (`BifrostModelCatalogue.list_models`)

1. Serve from cache if unexpired; otherwise take the lock and re-check, so concurrent
   callers single-flight
   ([`boltrig/fleet/bifrost_model_catalogue.py:275`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"async with self._lock:"`). The cached value is deep-copied on both store and return.
2. Run every page and body read inside ONE wall-clock deadline of 1.5s
   ([`boltrig/fleet/bifrost_model_catalogue.py:288`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"async with asyncio.timeout(BIFROST_CATALOGUE_TIMEOUT_SECONDS):"`).
   *Failure branch:* `unavailable("gateway_timeout")`.
3. Build the URL. Only `http`/`https`, only hosts in
   `{bifrost, localhost, 127.0.0.1, ::1}`, no userinfo, no query, no fragment, path
   exactly `/v1` or `/v1/`
   ([`boltrig/fleet/bifrost_model_catalogue.py:103`](../../../boltrig/fleet/bifrost_model_catalogue.py) `or split.path not in {"/v1", "/v1/"}`).
   *Failure branch:* `unavailable("not_configured")` or `"invalid_gateway_configuration"`.
4. Build the bearer header from `BOLTRIG_MODEL_GATEWAY_KEY`; a key longer than 4096 bytes
   or containing a non-printable-ASCII byte yields `None` and the whole call is
   `invalid_gateway_configuration`
   ([`boltrig/fleet/bifrost_model_catalogue.py:114`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"if len(key) > 4096 or any(ord(character) < 0x21"`).
5. Fetch each page with `accept-encoding: identity`, redirects off, `trust_env=False`,
   counting RAW transport bytes so a compressed bomb cannot expand past the cap
   ([`boltrig/fleet/bifrost_model_catalogue.py:144`](../../../boltrig/fleet/bifrost_model_catalogue.py) `async with client.stream("GET", url, headers=request_headers)`).
   *Failure branches, all typed:* `response_too_large`, `gateway_response_rejected`
   (encoded body, 3xx, non-2xx, non-int status, non-bytes body), `gateway_unavailable`
   (any other transport error), `schema_invalid`, `catalogue_too_large`,
   `pagination_limit`.
6. Parse strictly: JSON with `parse_constant` rejecting non-finite constants, a `data`
   list, unique ids per page, bounded text with no control/format/surrogate/line-separator
   characters, at most 8 unique modalities of at most 32 chars each, and a cursor drawn
   only from `[A-Za-z0-9_-]` up to 2048 chars
   ([`boltrig/fleet/bifrost_model_catalogue.py:233`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"next page token is outside the bounded cursor format"`).
7. Paginate at most 8 pages of 100, refusing a repeated cursor, an empty page with a
   cursor, or a cross-page duplicate id. Partial results are NEVER retained
   ([`boltrig/fleet/bifrost_model_catalogue.py:79`](../../../boltrig/fleet/bifrost_model_catalogue.py) `"partial catalogue data is never retained"`).

### 5.3 Catalogue admission (`catalogue_model_reason`)

The shared fail-closed decision, one function, five reasons
([`boltrig/model_catalogue_policy.py:42`](../../../boltrig/model_catalogue_policy.py) `"def catalogue_model_reason("`):

1. Not a dict, or `status != "ok"`, or `models` not a list: `catalogue_unavailable`.
2. More than one row with this exact id: `catalogue_unavailable` (a duplicate snapshot is
   an unusable snapshot).
3. No row: `model_not_advertised`. Display names and aliases never match; only `id` does.
4. `input_modalities` absent or malformed: the store endpoint's OWN declaration may stand
   in, but ONLY when the key is absent entirely, never when it is present and malformed
   ([`boltrig/model_catalogue_policy.py:30`](../../../boltrig/model_catalogue_policy.py) `if "input_modalities" in row:`). Otherwise `text_capability_not_advertised`.
5. Required modalities not a subset: `text_not_supported` when text was required, else
   `modality_not_supported`. `vision` is mapped to `image` on both sides
   ([`boltrig/model_catalogue_policy.py:80`](../../../boltrig/model_catalogue_policy.py) `required = {"image" if modality == "vision" else modality`).

At runtime admission, `require_catalogue_model` converts a `None` catalogue, a raising
catalogue, or a `catalogue_unavailable` reason into `ModelCatalogueUnavailable`, and every
other reason into `ModelEndpointUnavailable`
([`boltrig/fleet/codex_model_selection.py:143`](../../../boltrig/fleet/codex_model_selection.py) `"the exact model is not advertised for the requested input by Bifrost"`).

### 5.4 Governed endpoint authoring (`control.model_endpoint.*`)

1. `approval_context` runs `preflight_model_endpoint_catalogue` BEFORE raising the HITL
   approval, so an unprovable Bifrost row is refused without burning a human decision
   ([`boltrig/config/control_plane.py:124`](../../../boltrig/config/control_plane.py) `"await preflight_model_endpoint_catalogue("`). The preflight returns early for
   anything that is not a standard `bifrost`/`xai`/`x.ai`/`grok` row
   ([`boltrig/config/control_model_endpoints.py:98`](../../../boltrig/config/control_model_endpoints.py) `if data_class != "standard" or kind not in {"bifrost", "xai", "x.ai", "grok"}:`).
2. On execute, the id is re-parsed as an opaque choice id; the approval context is
   re-proved unchanged; the fallback is validated (not self, exists, active).
3. `data_class == "sensitive"` requires `kind == "local"`, else `ControlConflict`
   ([`boltrig/config/control_model_endpoints.py:178`](../../../boltrig/config/control_model_endpoints.py) `if data_class == "sensitive" and kind != "local":`).
4. A standard `bifrost`/`xai` row must carry an exact immutable model id; a standard
   `bifrost` row must additionally be catalogue-proven for its declared modalities.
5. The write is a compare-and-swap against the approved endpoint snapshot, the approved
   fallback target, AND the approved reference snapshot (the set of capabilities pointing
   at it plus the set of endpoints falling back to it); any drift returns "model endpoint
   changed after approval"
   ([`boltrig/config/control_model_endpoints.py:208`](../../../boltrig/config/control_model_endpoints.py) `raise ControlConflict("model endpoint changed after approval")`).
6. Retire/restore go through `compare_and_set_model_endpoint_active` with the same
   approval binding. An ordinary replacement upsert preserves the current `is_active`, so
   editing a retired row cannot smuggle it back into service
   ([`boltrig/store/model_endpoints_postgres.py:181`](../../../boltrig/store/model_endpoints_postgres.py) `"current.is_active if current else endpoint.is_active,"`).

### 5.5 Scoped BYO provider binding (`BifrostUserGateway.ensure`)

1. Validate the provider key is printable ASCII, then load and health-check any existing
   binding; if usable, return it. Take the lock and re-check (double-checked idempotence).
2. Resolve `(provider, raw_model, model_id)`. A provider in `BIFROST_PROVIDERS` (23 names)
   rides Bifrost's native driver; any other well-formed catalogue provider id is bound as
   an OpenAI-compatible CUSTOM provider
   ([`boltrig/identity/bifrost_user_binding.py:87`](../../../boltrig/identity/bifrost_user_binding.py) `"CUSTOM provider instead - Bifrost stores its ``base_url`` in"`).
   *Failure branch:* a custom provider with no base URL is refused with the actionable
   half of the sentence, "because an address is the one thing the custom path cannot
   invent"
   ([`boltrig/identity/bifrost_user_binding.py:119`](../../../boltrig/identity/bifrost_user_binding.py) `needs the URL of its OpenAI-compatible endpoint; "`).
3. `ensure_provider`: list providers, and for a custom provider write the address into
   BOTH `network_config.base_url` and `custom_provider_config.base_url`, because "Bifrost
   silently drops it from custom_provider_config"
   ([`boltrig/identity/bifrost_user_admin.py:262`](../../../boltrig/identity/bifrost_user_admin.py) `"base_url must go in NETWORK_CONFIG - Bifrost silently drops it"`). Reading back uses
   `stored_base_url`, which checks `network_config` FIRST
   ([`boltrig/identity/bifrost_user_transport.py:220`](../../../boltrig/identity/bifrost_user_transport.py) `for key in ("network_config", "custom_provider_config"):`).
   *Failure branch:* an existing custom row at a DIFFERENT address is refused rather than
   silently re-pointed, "the kind of quiet cross-tenant surprise this module refuses"
   ([`boltrig/identity/bifrost_user_admin.py:232`](../../../boltrig/identity/bifrost_user_admin.py) `"quiet cross-tenant surprise this module refuses"`); an addressless row says so and
   asks for a re-add.
4. `ensure_provider_key`: POST when absent, PUT when present with a matching id, refuse
   when a conflicting key exists. A self-hosted provider named in
   `_PROVIDER_URL_CONFIG = {"ollama": "ollama_key_config"}` must carry its server URL in
   that provider-specific block, else Bifrost 400s with a message the operator cannot act
   on ([`boltrig/identity/bifrost_user_admin.py:302`](../../../boltrig/identity/bifrost_user_admin.py) `"required for Ollama keys"`, a 400 the operator cannot act on).
5. `ensure_virtual_key`: one virtual key per derived name, scoped to
   `{provider, allowed_models: [raw_model], key_ids: [provider_key_id]}`; a mismatched
   existing key is deleted and recreated; duplicates are refused.
6. Prove the binding usable by listing `/v1/models?provider=...` with the virtual key over
   at most 8 pages. *Failure branch:* ask the gateway which failure it was and split the
   message, because "a key whose provider fetch failed is a wrong ADDRESS; a healthy key
   whose listing lacks the id is a wrong NAME"
   ([`boltrig/identity/bifrost_user_binding.py:255`](../../../boltrig/identity/bifrost_user_binding.py) `"whose provider fetch failed is a wrong ADDRESS"`).
7. Seal `{store: "bifrost", ref: virtual_key_id, secret: virtual_key, provider, model_id,
   source_credential_ref, provider_key_id, virtual_key_id}` into `credential_refs`.

### 5.6 Cost accounting

1. **Pre-run estimate.** `estimate(task, prompt, skills, cost_tier)` is deterministic:
   `tokens = max(16, chars // 4)`, priced by `price_micros(tokens, cost_tier)` with NO
   model, hence always at the tier rate
   ([`boltrig/fleet/spawn_budget.py:19`](../../../boltrig/fleet/spawn_budget.py) `"return tokens, price_micros(tokens, cost_tier)"`).
2. **Reserve.** `CostAccountant.reserve` reads each scope's budget, fails fast if any
   hard-stop scope lacks headroom, fires the 80 percent alert as a fail-safe side channel,
   then commits through the store's atomic all-or-nothing multi-scope reserve
   ([`boltrig/kernel/cost.py:316`](../../../boltrig/kernel/cost.py) `"windows = await self._store.reserve_budgets_atomic("`).
   *Failure branch:* `BudgetExceeded`; a run-window budget read outside a run raises
   `BudgetWindowUnavailable`.
3. **Capture usage.** The Codex runtime records `total_tokens` and, when present,
   positive-int `input_tokens`/`output_tokens` legs from `thread/tokenUsage/updated`
   ([`boltrig/fleet/codex_runtime_support.py:126`](../../../boltrig/fleet/codex_runtime_support.py) `legs["input_tokens"] = _reported_leg(payload.get("input_tokens"))`). A non-int or
   non-positive leg becomes 0.
4. **Price the actual.** `_true_up_cost` looks up `capability.model_endpoint` in the store
   and uses THAT row's `model` as the price key, then prices leg by leg
   ([`boltrig/fleet/spawn.py:390`](../../../boltrig/fleet/spawn.py) `"actual_micros = self._kernel.cost.price("`). See RISK-1004: this is not necessarily
   the model that served.
5. **Reconcile.** Apply the signed `(actual - estimate)` delta to every reserved window;
   a zero delta short-circuits
   ([`boltrig/kernel/cost.py:347`](../../../boltrig/kernel/cost.py) `"if delta_tokens == 0 and delta_micros == 0:"`). Reconcile never re-checks the hard
   stop and never alerts: "it corrects the record of a call that already ran".

## 6. Data

### 6.1 `model_endpoints`

[`boltrig/store/schema.sql:373`](../../../boltrig/store/schema.sql) `"CREATE TABLE IF NOT EXISTS model_endpoints ("`

| column | type | notes |
| --- | --- | --- |
| `id` | TEXT NOT NULL | part of PK |
| `tenant_id` | TEXT NOT NULL | part of PK |
| `kind` | TEXT NOT NULL | schema comment lists `anthropic | openai | ollama | vllm` and omits `bifrost` and `local` |
| `base_url` | TEXT | nullable |
| `model` | TEXT NOT NULL | |
| `fallback` | TEXT | soft reference, no FK |
| `data_class` | TEXT NOT NULL DEFAULT 'standard' | `standard | sensitive` |
| `modalities` | JSONB NOT NULL DEFAULT `'["text"]'` | migration 0069 |
| `is_active` | BOOLEAN NOT NULL DEFAULT TRUE | migration 0048 |
| `revision` | BIGINT NOT NULL DEFAULT 1 | migration 0071 |
| `created_at`, `updated_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| PK | `(tenant_id, id)` | |

There are NO indexes beyond the primary key on this table, and no foreign key on
`fallback`. Every read is by `(tenant_id, id)` or a full `tenant_id` scan ordered by `id`
([`boltrig/store/model_endpoints_postgres.py:213`](../../../boltrig/store/model_endpoints_postgres.py) `"SELECT * FROM model_endpoints WHERE tenant_id=$1 ORDER BY id"`).

**Migrations.** `0048_model_endpoint_lifecycle` adds `is_active`;
`0069_agent_model_modalities` adds `modalities` here and `vision_model_endpoint` on
`agent_capabilities`; `0071_model_endpoint_revision` adds `revision`. All three are
`ADD COLUMN IF NOT EXISTS` with matching `DROP COLUMN IF EXISTS` downgrades.

**RLS.** `model_endpoints` is in the hand-maintained fence list of the RLS overlay
([`boltrig/store/rls.sql:79`](../../../boltrig/store/rls.sql) `"'workflow_definitions','model_endpoints','work_items','hitl_requests',"`), which enables
and forces row-level security with a `tenant_id = current_setting('app.tenant_id', true)`
policy. No migration under `migrations/versions/` enables RLS on this table (bounded:
`rg "model_endpoints" migrations/`, which returns only 0048, 0069, 0071 and
`baseline.sql`); the overlay is the mechanism.

**Concurrency.** Every mutating path takes a tenant-scoped Postgres advisory transaction
lock keyed `model-endpoints:{tenant}` before reading the reference graph
([`boltrig/store/model_endpoint_contract.py:19`](../../../boltrig/store/model_endpoint_contract.py) `"SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"`), so an endpoint edit is
serialised against capability and fallback reference writes. Every upsert bumps
`revision`, and changing a fallback also bumps the revision of the OLD and NEW fallback
targets so their in-flight approvals invalidate.

**Encryption and retention.** No encryption at this layer; `base_url` is stored in
plaintext and never projected to a browser (see 7.4). No retention or expiry: rows are
retired, not deleted, and retirement is reversible.

### 6.2 The price table

Not a table. It is process memory on `CostAccountant._prices`, seeded from
`manifest.models.prices` at `apply_manifest`
([`boltrig/config/manifest_apply.py:180`](../../../boltrig/config/manifest_apply.py) `"cost.set_prices(manifest.models.prices)"`), and mutated one model at a time by the
distill promotion path (`set_price`). Changing it requires a process restart or a
manifest apply; the platform route says so
([`boltrig/kernel/platform_routes/model_endpoints.py:124`](../../../boltrig/kernel/platform_routes/model_endpoints.py) `"changes_apply_at": "process_restart",`).

### 6.3 The conversation binding table

Not persisted. In-process dict, TTL and size bounded (4.6). It survives neither restart
nor a second replica: two kernel replicas hold independent binding tables, so the same
conversation may pin different models on different replicas.

### 6.4 The Bifrost binding credential row

Sealed into `credential_refs` under `bifrost_binding:{sha256}`. The stored dict holds the
VIRTUAL key (a narrowed, model-scoped credential), never the user's provider key
([`boltrig/identity/bifrost_user_binding.py:273`](../../../boltrig/identity/bifrost_user_binding.py) `"store": "bifrost",`).

## 7. Configuration surface

### 7.1 Environment

| var | default | read by | what breaks if wrong |
| --- | --- | --- | --- |
| `BOLTRIG_MODEL_GATEWAY_URL` | unset (seam inert) | `gateway_config`, `BifrostModelCatalogue`, `BifrostUserTransport` | Unset: no gateway re-point, no catalogue (`not_configured`), automatic Codex routing refuses, model choices refuse. Set to a non-internal host or a path other than `/v1`: catalogue returns `invalid_gateway_configuration` and the admin transport raises "the model gateway configuration is invalid" ([`boltrig/identity/bifrost_user_transport.py:45`](../../../boltrig/identity/bifrost_user_transport.py) `"the model gateway configuration is invalid"`). |
| `BOLTRIG_MODEL_GATEWAY_TTL` | `900` | `gateway_config` | Sets the conversation binding TTL, clamped to a minimum of 1 second. A TTL out of step with Bifrost's own cache window either pins a cold cache or re-routes a warm one. |
| `BOLTRIG_MODEL_GATEWAY_KEY` | unset | catalogue bearer, `BifrostUserTransport.inference_headers` | Over 4096 bytes or non-printable: catalogue becomes `invalid_gateway_configuration`. Unset in dev is expected (the dev bifrost is unauthenticated). |
| `BOLTRIG_BIFROST_MANAGEMENT_KEY` | `""` | `BifrostUserTransport._admin_headers` | The only bearer on Bifrost ADMIN calls. Not present in `.env.example` (bounded: `grep -rn "BOLTRIG_BIFROST_MANAGEMENT_KEY"` over the tree returns exactly one hit, the reader). |
| `BOLTRIG_MODEL_GATEWAY_HEALTH` | unset | `gateway_posture`, `ModelGatewayStatusProvider` | Arms an actual health probe. Deliberately a boolean, distinct from the URL which is configured by presence, because manifest export writes `"0"` for an explicit disabled posture. |
| `BOLTRIG_MODEL_GATEWAY_HEALTH_URL` / `_PATH` / `_TIMEOUT` | unset / `/health` / `0.75` | `_health_url`, `_float_env` | An external health host is refused without polling (`external_host_rejected`). |
| `BOLTRIG_MODEL_PROFILES` | unset | `visible_model_profiles`, `resolve_realtime_model_profile` | A JSON object of voice profiles; malformed JSON silently yields zero profiles. |
| `BIFROST_PORT` | `8081` | compose | Host loopback port for the Bifrost admin/API surface. |
| `LOCAL_MODEL` | `Qwen/Qwen2.5-7B-Instruct` | compose `local-model` command | The vLLM model the on-box service serves. |
| `LOCAL_MODEL_PORT` | `8001` | compose | Loopback convenience port; the secure overlay removes it. |
| `LOCAL_MODEL_CACHE` | `./.models` | compose | Host path for the HF cache so an air-gapped box never reaches the internet. |
| `AIR_GAPPED` | `false` | `doctor` | When true, doctor fails (production) or warns on any hosted standard endpoint. |
| `BOLTRIG_CODEX_MODEL` | unset | trusted Codex config | Becomes `codex_config["model_id"]`, the automatic route's model and the chat default label. |

Manifest-only interpolation variables used by `manifest.example.yaml` and by nothing
else (bounded: `grep -rn` over `.env.example`, `docker-compose.yml`, `genesis.sh`):
`BOLTRIG_DEFAULT_MODEL`, `BOLTRIG_LOCAL_MODEL`, `BOLTRIG_LOCAL_MODEL_URL`. None has a
default anywhere, so the shipped manifest resolves both endpoints' `model:` to the empty
string ([`boltrig/config/manifest.py:452`](../../../boltrig/config/manifest.py) `return env.get(name, default if default is not None else "")`).

### 7.2 Manifest keys

```
models:
  endpoints: [{id, kind, model, base_url, fallback, data_class, modalities}]
  default: <endpoint id>            # parsed, projected, NO serving consumer
  sensitive_endpoint: <endpoint id> # the local role
  prices: {<model name>: <float> | {input: <float>, output: <float>}}
runtimes:
  gateway: {base_url, cache_ttl_seconds, health: {enabled, path, timeout}, model_profiles}
memory:
  embedding_endpoint, extraction_endpoint, local_endpoints
```

`_parse_models` applies NO validation beyond `ModelEndpoint.__post_init__`: `kind`
defaults to `"anthropic"`, `data_class` defaults to `"standard"`, and there is no
sensitive-implies-local check on this path
([`boltrig/config/manifest.py:577`](../../../boltrig/config/manifest.py) `"ModelEndpoint("`). See RISK-1001.

`_parse_price` drops a malformed entry rather than failing load, "so a bad price never
blocks boot"; the model then falls back to its cost tier
([`boltrig/config/manifest.py:591`](../../../boltrig/config/manifest.py) `"rather than failing load, so a bad price never blocks boot"`). A mapping keeps whichever
legs parse; an entry with no usable leg is dropped whole, deliberately, because a silent
zero also bypasses the budget ceiling check.

The price KEY is the endpoint's `model:` string, not the endpoint id, and the manifest
says so at length, including the warning that the same model on two providers has two
rate cards ([`manifest.example.yaml:109`](../../../manifest.example.yaml) `"THE KEY IS THE MODEL NAME; THE RATE IS THE PROVIDER'S."`).

### 7.3 Compose services

`bifrost`: profile `gateway`, digest-pinned `maximhq/bifrost`, on both `default` and
`sandbox` networks, loopback-only host port
([`docker-compose.yml:517`](../../../docker-compose.yml) `profiles: ["gateway"]`).
Config (providers, routing, cache) persists in the `bifrost_data` volume; there is no
config file, it is administered through its own UI/API.

`local-model`: profile `local`, digest-pinned `vllm/vllm-openai:v0.24.0-ubuntu2404`,
OpenAI-compatible on `:8000`, `ipc: host`, an optional nvidia GPU reservation, and a
mounted HF cache ([`docker-compose.yml:537`](../../../docker-compose.yml) `profiles: ["local"]`). The comment states the CPU-only escape hatch: "On a CPU-only
box, swap this image for an Ollama service"
([`docker-compose.yml:557`](../../../docker-compose.yml) `"# GPU is optional. On a CPU-only box, swap this image for an Ollama service."`).

The `sandbox` network is a plain bridge in the base file and only becomes `internal: true`
under the secure overlay; the base file warns about this in place
([`docker-compose.yml:749`](../../../docker-compose.yml) `"WARNING: the base docker-compose.yml is a dev stack."`). The secure overlay additionally
strips the published ports of both `bifrost` and `local-model`
([`deploy/compose.secure.yml:69`](../../../deploy/compose.secure.yml) `"ports: !override []"`).

### 7.4 What is never projected

`GET /v1/model-policy` returns role states, eligibility, prices and a generation digest,
and no base URL, host, or credential; the test asserts the absence of the endpoint's host
and path from the whole response body
([`tests/security/test_model_endpoint_lifecycle.py:862`](../../../tests/security/test_model_endpoint_lifecycle.py) `assert "private-model.example.test" not in response.text`).
`GET /v1/model-endpoints` (list) omits `base_url` and `fallback`; only the author-only
detail route hydrates them
([`boltrig/kernel/platform_routes/model_endpoints.py:151`](../../../boltrig/kernel/platform_routes/model_endpoints.py) `"The general picker omits topology details."`).
`GET /v1/chat/model-choices` returns the exact model NAME plus an opaque choice id and
catalogue-derived availability, and filters to active, standard, text-capable rows
([`boltrig/kernel/platform_routes/chat_model_choices.py:255`](../../../boltrig/kernel/platform_routes/chat_model_choices.py) `and endpoint.data_class == "standard"`).
`GET /v1/bifrost/models` is author-only and re-projects even an injected provider so extra
upstream fields cannot escape
([`boltrig/kernel/platform_routes/bifrost_models.py:42`](../../../boltrig/kernel/platform_routes/bifrost_models.py) `"Re-project even an injected provider so extra upstream fields cannot escape."`).

## 8. PROCESS

### 8.1 Bringing the model lane up from nothing

1. `cp .env.example .env` and `cp manifest.example.yaml manifest.yaml`
   ([`README.md:130`](../../../README.md) `"cp .env.example .env                 # then edit secrets"`).
2. `make up` starts the default stack WITHOUT the gateway and WITHOUT the local model.
   `make up ARGS="--profile local"` adds on-box inference
   ([`Makefile:38`](../../../Makefile) `add ARGS="--profile local" for on-box inference`).
3. `docker compose --profile gateway up -d` starts Bifrost, then set
   `BOLTRIG_MODEL_GATEWAY_URL=http://bifrost:8080/v1` in `.env` and configure provider
   keys in Bifrost's own UI on `http://localhost:8081`
   ([`.env.example:248`](../../../.env.example) `"service), configure provider keys in the Bifrost UI at http://localhost:8081,"`).
   Boltrig never holds those provider keys.
4. `./genesis.sh` automates the gateway half: it forces `--profile gateway`, sets
   `BIFROST_PORT`, `BOLTRIG_MODEL_GATEWAY_URL` and `BOLTRIG_MODEL_GATEWAY_TTL`, adds
   `bifrost,local-model` to `NO_PROXY`, and copies the example manifest if none exists
   ([`genesis.sh:28`](../../../genesis.sh) `"COMPOSE_PROFILES=(--profile gateway)"`).
   It does NOT start the `local` profile.
5. In Worker, choose one of Bifrost's advertised text models under
   **Settings -> Models**, which reads `GET /v1/chat/model-choices` and
   `GET /v1/model-policy`
   ([`README.md:146`](../../../README.md) `"Codex→Bifrost path gives Boltrig only an opaque governed route and exact model"`).

### 8.2 Verifying posture before deploying

`make doctor` (add `ARGS="--production"` for deploy-blocking severity) runs the static
checks ([`Makefile:478`](../../../Makefile)
`"$(PY) -m boltrig.api.cli doctor --env-file .env --manifest manifest.yaml $(ARGS)"`).
The model checks it performs, in order
([`boltrig/api/doctor.py:404`](../../../boltrig/api/doctor.py) `"def _check_model_posture("`):

- `model_endpoints`: fail (production) or warn if the manifest declares none.
- `sensitive_endpoint`: fail/warn if `models.sensitive_endpoint` names no declared
  endpoint; **fail** if the named endpoint is not `data_class=sensitive`; ok otherwise.
- `sensitive_endpoint_host`: warn when the sensitive endpoint's `base_url` host is not
  obviously local or internal.
- `air_gapped_models`: when `AIR_GAPPED` or `network.air_gapped`, fail/warn on any hosted
  standard endpoint whose host is not local.
- `model_gateway`: fail on a malformed URL, warn when the URL lacks `/v1` or the host is
  not obviously internal.
- `memory_residency`: **fail** unless every configured memory embedding/extraction
  endpoint is in the declared local set AND is `data_class=sensitive`
  ([`boltrig/api/doctor.py:486`](../../../boltrig/api/doctor.py) `or endpoints[endpoint_id].data_class != "sensitive"`).

Note what doctor does NOT check: it never asserts `kind == "local"` for the sensitive
endpoint, so the shipped manifest passes doctor while failing the platform route's
eligibility test (RISK-1002).

### 8.3 Changing an endpoint in a live tenant

Endpoint mutation is a governed control verb, not a database write. From Worker:
`POST /v1/model-endpoints/{id}/retire` or `/restore` returns `202 pending_human` with a
`hitl_request_id`; an independent reviewer answers it; the caller replays with
`x-boltrig-approval-id` and receives `200` with the new status
([`tests/security/test_model_endpoint_lifecycle.py:873`](../../../tests/security/test_model_endpoint_lifecycle.py) `"def test_direct_endpoint_route_finalizes_with_caller_held_approval"`). Both routes
require an author role. If the endpoint changed between approval and replay, the
compare-and-swap refuses and a fresh approval is required.

### 8.4 Recovering from a refused route

- `403 sensitive_data_misrouted`: there is no active `data_class=sensitive` endpoint the
  request can reach. Fix the manifest's `sensitive_endpoint`, apply it, and restart the
  process (the sensitive role is pinned at composition, step 5.1.2). Bringing up
  `--profile local` alone is not enough if no endpoint ROW names it.
- `409 model_endpoint_unavailable`: a named endpoint is missing or retired. Restore it
  through the governed lifecycle route; do not add a fallback and expect the router to
  follow it.
- `503 model_catalogue_unavailable`: Bifrost is unreachable or misconfigured. Check
  `BOLTRIG_MODEL_GATEWAY_URL` points at an internal host on an exact `/v1` path, then
  `GET /v1/bifrost/models` as an author to read the typed reason.
- Chat model choices all `unavailable`: read `default_unavailable_reason`, which
  distinguishes `trusted_codex_unavailable`, `model_gateway_unavailable`,
  `provider_not_connected`, `model_not_advertised`, `model_id_unsupported`,
  `text_capability_not_advertised`, `text_not_supported` and `catalogue_unavailable`.

### 8.5 Diagnosing the gateway

`GET /v1/platform/status` carries a redacted `bifrost` component and a `model-gateway`
runtime with `configured`, `routing`, `internal_route`, `v1_base`, `live_health`,
`cache_ttl_seconds` and `profile_count`, and never a URL or key
([`boltrig/fleet/model_gateway_status.py:182`](../../../boltrig/fleet/model_gateway_status.py) `"id": "bifrost",`). `/readyz` reports the gateway as `unchecked` with reason
`configured_but_health_check_disabled` when a URL is set but no probe is armed, which
exists specifically because the old `disabled` reading hid a face-down Bifrost on a live
stack ([`boltrig/fleet/model_gateway.py:165`](../../../boltrig/fleet/model_gateway.py) `"THE DEFECT THIS EXISTS TO FIX (found on Classical Visas, 2026-07-26)."`).

## 9. Failure modes and fail-open/fail-closed posture

| guard | direction | proof |
| --- | --- | --- |
| Sensitive payload, no sensitive endpoint | **fail-closed**, audited 403 | [`boltrig/fleet/model_router.py:134`](../../../boltrig/fleet/model_router.py) `"raise SensitiveDataMisrouted("` |
| Named endpoint missing or retired | **fail-closed**, audited 409, no fallback traversal | [`boltrig/fleet/model_router.py:173`](../../../boltrig/fleet/model_router.py) `"raise ModelEndpointUnavailable("` |
| Endpoint does not advertise the modality | **fail-closed**, audited 409 | [`boltrig/fleet/model_router.py:102`](../../../boltrig/fleet/model_router.py) `"raise ModelEndpointUnavailable("` |
| Caller says "not sensitive" but the payload carries PII | **fail-closed** (scanner ORs in) | [`boltrig/fleet/codex_model_selection.py:73`](../../../boltrig/fleet/codex_model_selection.py) `"sensitive = sensitive or outbound_text_classifies_sensitive"` |
| Catalogue unreachable, malformed, duplicated, oversized, redirected, compressed, or paginating forever | **fail-closed**, typed unavailable, zero partial rows | [`boltrig/fleet/bifrost_model_catalogue.py:81`](../../../boltrig/fleet/bifrost_model_catalogue.py) `return {"status": "unavailable", "models": [], "reason": reason}` |
| Catalogue row lacking `input_modalities` | **fail-closed with one narrow exception**: the store's own declaration stands in ONLY when the key is absent | [`boltrig/model_catalogue_policy.py:30`](../../../boltrig/model_catalogue_policy.py) `if "input_modalities" in row:` |
| Model choice on a sensitive or pinned request | **fail-closed** | [`boltrig/fleet/codex_model_selection.py:46`](../../../boltrig/fleet/codex_model_selection.py) `"raise ModelEndpointUnavailable("` |
| Automatic Codex routing with no gateway | **fail-closed** | [`boltrig/fleet/codex_model_selection.py:197`](../../../boltrig/fleet/codex_model_selection.py) `"automatic Codex routing requires the Bifrost gateway"` |
| Trusted Codex not configured at all | **degrades**: returns `None`, the runtime becomes a typed-unavailable lane, no speculative model route is attached | [`boltrig/fleet/codex_model_selection.py:194`](../../../boltrig/fleet/codex_model_selection.py) `"if not trusted_codex_configured(codex_config):"` |
| Malformed exact model id in the Codex config | **degrades to `None`** rather than raising | [`boltrig/fleet/codex_model_selection.py:201`](../../../boltrig/fleet/codex_model_selection.py) `"return None"` |
| Gateway URL unset | **fail-open by design (inert)**: routing behaves exactly as before the seam existed | [`boltrig/fleet/model_gateway.py:17`](../../../boltrig/fleet/model_gateway.py) `"When no gateway URL is configured the seam is inert"` |
| Gateway configured but no health probe armed | **honest-unknown**, not `disabled` | [`boltrig/fleet/model_gateway.py:184`](../../../boltrig/fleet/model_gateway.py) `return ("unchecked", "configured_but_health_check_disabled")` |
| Gateway health probe raises | **fail-safe to `down`**, no crash | [`boltrig/fleet/model_gateway_status.py:224`](../../../boltrig/fleet/model_gateway_status.py) `return "down", {**meta, "health_error": "probe_failed"}` |
| Malformed price entry in the manifest | **fail-open to the tier default**: dropped at parse, boot continues | [`boltrig/config/manifest.py:591`](../../../boltrig/config/manifest.py) `"rather than failing load, so a bad price never blocks boot"` |
| Runtime reports a bare token total, no split | **fail-safe toward under-billing**: the whole total is charged at the INPUT rate, never free | [`boltrig/kernel/cost.py:137`](../../../boltrig/kernel/cost.py) `"# Unattributed tokens are billed at the INPUT rate, not the higher leg."` |
| Budget alert callback raises | **fail-safe**: logged at debug, reservation proceeds | [`boltrig/kernel/cost.py:302`](../../../boltrig/kernel/cost.py) `"except Exception:  # alert side-channel must never break reserve (P9)"` |
| Concurrent reserve consumes headroom between read and commit | **fail-closed**, all-or-nothing | [`boltrig/kernel/cost.py:322`](../../../boltrig/kernel/cost.py) `"if windows is None:"` |
| Existing custom Bifrost provider at a different address | **fail-closed**, refuses to re-point | [`boltrig/identity/bifrost_user_admin.py:257`](../../../boltrig/identity/bifrost_user_admin.py) `is already bound to a different endpoint; "` |
| Bifrost admin/inference response: redirect, non-identity encoding, oversized, non-JSON, non-object | **fail-closed** to `BifrostUserBindingUnavailable` | [`boltrig/identity/bifrost_user_transport.py:167`](../../../boltrig/identity/bifrost_user_transport.py) `"Bifrost redirect was rejected"` |
| Sensitive memory write whose endpoint is not in the declared local set | **fail-closed**, audited 403 | [`boltrig/memory/adapter_writes.py:73`](../../../boltrig/memory/adapter_writes.py) `if data_class == "sensitive" and self._sensitive_endpoint not in self._local_endpoints:` |
| Distillation corpus targeting a standard endpoint | **fail-closed** | [`boltrig/distill/corpus.py:219`](../../../boltrig/distill/corpus.py) `if target_data_class != "sensitive":` |

### 9.1 The doctrine claim, checked

`AGENTS.md` states "Sensitive data is gated to local endpoints by the model router"
([`AGENTS.md:36`](../../../AGENTS.md) `"Sensitive data is gated to local endpoints by the model router"`), and
`docs/architecture/engine-components.md` says of the router "**Public surface.** None;
runs inside every spawn"
([`docs/architecture/engine-components.md:385`](../../../docs/architecture/engine-components.md) `"None; runs inside every spawn."`).

**The claim holds for the spawn/chat lane and is verified.** `select_model_endpoint` is
called from exactly one production module, `boltrig/fleet/codex_model_selection.py`, at
two sites, and every ephemeral and permanent spawn reaches it through
`RuntimeResolver.runtime_for -> _resolve_runtime_policy_with_binding -> resolve_base_model`
(bounded: `rg -n "select_model_endpoint" .` over the pinned tree returns
`boltrig/fleet/model_router.py` plus two call sites in
`boltrig/fleet/codex_model_selection.py` and two test files, 2026-08-24). The refusal when the local role is absent is exercised
directly by `tests/security/test_sensitive_routing.py::test_pii_bearing_payload_without_local_endpoint_fails_closed`,
which passes `sensitive_endpoint_id=None` with a hosted capability endpoint and asserts
both the raise and the audit row
([`tests/security/test_sensitive_routing.py:141`](../../../tests/security/test_sensitive_routing.py) `"with pytest.raises(SensitiveDataMisrouted):"`). There is no branch in
`select_model_endpoint` that returns a standard endpoint once `sensitive` is true: the
function either returns a `data_class == "sensitive"` row or raises.

**The claim is narrower than "every model call".** Three production model-egress paths in
the pinned tree never consult the router, `data_class`, or the PII classifier:

1. **Knowledge/Cognee compilation.** `CogneeModelBindingResolver.resolve` goes straight
   from `resolve_ai_key` to a Bifrost virtual key and hands Cognee an OpenAI-compatible
   route ([`boltrig/memory/cognee_model_binding.py:65`](../../../boltrig/memory/cognee_model_binding.py) `"endpoint, api_key, headers = transport.openai_compatible_route(binding.virtual_key)"`),
   reached from `KnowledgeProjectionCoordinator._runtime_model`
   ([`boltrig/knowledge/projections.py:150`](../../../boltrig/knowledge/projections.py) `"return await self._model_resolver.resolve(tenant_id, context)"`).
2. **Realtime voice.** `resolve_call_profiles` resolves an endpoint by the `realtime`
   modality and requires `kind` in `{xai, x.ai, grok}`, an external provider, with no
   `data_class` test ([`boltrig/kernel/call_profiles.py:51`](../../../boltrig/kernel/call_profiles.py) `and endpoint.kind.lower() in {"xai", "x.ai", "grok"}`).
3. **Memory writes**, which use their own name-set guard rather than the router (9, and
   RISK-1003).

Bounded search supporting this: `rg -n "data_class" boltrig/` excluding
`boltrig/models/` returns readers only in `distill/`, `api/doctor.py`,
`config/control_model_endpoints.py`, `config/control_approval_model_endpoints.py`,
`config/manifest.py`, `store/`, `kernel/platform_routes/model_endpoints.py`,
`kernel/platform_routes/chat_model_choices.py`, `kernel/memory_read_routes.py` and
`kernel/federated_search_routes.py`. No `data_class` reader exists in `knowledge/`,
`kernel/call_profiles.py`, or `kernel/call_route_support.py` (2026-08-24, pinned tree).

## 10. What is proven

| invariant | binds | named tests |
| --- | --- | --- |
| `SEC-12` | Sensitive routes only to local; authoring rejects a sensitive non-local endpoint; runtime misroutes blocked and audited; an external AI config cannot move sensitive data off the local endpoint | `tests/security/test_sensitive_routing.py::test_sensitive_data_blocked_from_hosted_and_audited`, `::test_sensitive_data_routes_to_local_endpoint`, `::test_spawn_blocks_sensitive_on_hosted_capability`, `::test_ai_key_profile_cannot_override_governed_model_endpoint`, `::test_pii_bearing_payload_routes_local_despite_caller_classification`, `::test_clean_payload_still_routes_hosted`, `::test_pii_bearing_payload_without_local_endpoint_fails_closed`, `tests/security/test_model_endpoint_lifecycle.py::test_endpoint_authoring_enforces_local_sensitive_and_exact_bifrost_ids`, `::test_bifrost_authoring_requires_live_exact_catalogue_modalities` ([`tests/invariants.yaml:756`](../../../tests/invariants.yaml) `"SEC-12:"`) |
| `SEC-13` | The PII detector IS consulted on model egress FOR ROUTING and classifies only; `manifest.privacy.pii_redaction` is parsed and read by nothing | `tests/security/test_budget_and_pii.py::test_pii_redaction` ([`tests/invariants.yaml:899`](../../../tests/invariants.yaml) `"The detector IS consulted on model egress for ROUTING"`) |
| `SEC-43` | Sensitive memory must use a local endpoint; a misroute is blocked and audited | `tests/security/test_round_five.py::test_sensitive_memory_stays_local` |
| `SEC-47` | The gateway binds per conversation, pins one model across turns, never re-routes sensitive | `tests/security/test_round_six.py::test_gateway_binds_per_conversation_not_run`, `::test_gateway_never_reroutes_sensitive_and_is_inert_when_unset` |
| `FR-GW-01` | Bifrost is wired into the stack: profile-gated service on sandbox, genesis/dev start the profile, documented `/v1` URL matches | `tests/security/test_round_six.py::test_bifrost_is_wired_into_the_stack` |
| `FR-GW-03` | Platform status reports the gateway with cache/profile posture only, never URLs or keys | `tests/security/test_platform_status.py::test_model_gateway_status_is_bounded_and_redacted`, `::test_model_gateway_status_reports_inert_when_unconfigured` |
| `FR-GW-04` | Live health polling is internal-host-only, bounded, fail-safe | `tests/security/test_model_gateway_live_health.py::test_model_gateway_live_health_polls_internal_endpoint_and_redacts_payload`, `::test_model_gateway_live_health_rejects_external_hosts_without_polling`, `::test_model_gateway_live_health_probe_failure_degrades_not_crashes` |
| `FR-GW-05` | Catalogue discovery is author-only, read-only, redirect-free, proxy-free, bounded in time/body/rows/pages/cursor, and typed-unavailable on every failure | eight tests in `tests/security/test_bifrost_model_catalogue.py` ([`tests/invariants.yaml:1120`](../../../tests/invariants.yaml) `"FR-GW-05:"`) |
| `SEC-WRK-02` | A model selection is a preference among server-held approved endpoints, never a caller route or credential | `tests/security/test_chat_model_choices.py::test_chat_model_choices_are_tenant_scoped_exact_and_catalogue_verified`, `::test_catalogue_failure_marks_every_safe_choice_unavailable`, `::test_chat_rejects_blank_whitespace_and_oversized_choice_ids`, `tests/unit/test_runtime_resolver_codex.py::test_default_codex_route_uses_composed_model_not_capability_endpoint`, `::test_unavailable_codex_runtime_carries_no_speculative_model_route` |
| `SEC-WRK-14` | Endpoint withdrawal is recoverable and governed; direct routing, capability binding and fallback binding all fail closed for a retired row; a stored fallback never bypasses withdrawal; parity on both stores | six tests in `tests/security/test_model_endpoint_lifecycle.py` ([`tests/invariants.yaml:2512`](../../../tests/invariants.yaml) `"SEC-WRK-14:"`) |
| `FR-COST-02/03/04/05` | Hard stop halts before exceeding; the ledger trues up to actual; per-model rate wins over the tier; the multi-scope reserve is all-or-nothing | `tests/security/test_cost_trueup.py::test_budget_trued_up_to_actual_after_run`, `::test_degraded_run_refunds_the_estimate`, `::test_model_price_from_config_overrides_tier_default`, `::test_cost_tier_vocabulary_is_closed_across_manifest_and_control`, `tests/store/test_budget_atomic_reserve.py` (three tests) |
| store parity | endpoint lifecycle behaves identically in-memory and on Postgres | `tests/store/test_store_parity.py::test_model_endpoint_lifecycle_matches_on_both_stores` |

Additional named tests with no invariant binding recorded in `tests/invariants.yaml`
(bounded: `grep -n` for each file name in `tests/invariants.yaml`):
`tests/unit/test_bifrost_custom_provider_base_url.py` (7 tests over the custom-provider
base-url contract), `tests/unit/test_bifrost_selfhosted_key.py` (5 tests over
`ollama_key_config`), `tests/unit/test_model_catalogue_policy_declared.py` (7 tests over
the declared stand-in), `tests/unit/test_user_model_id_policy.py` (4 tests),
`tests/unit/test_readiness_gateway_posture.py`.

## 11. RISKS

- **RISK-1001: the manifest can author a sensitive endpoint of any kind.** The governed
  control verb refuses `data_class == "sensitive"` unless `kind == "local"`
  ([`boltrig/config/control_model_endpoints.py:179`](../../../boltrig/config/control_model_endpoints.py) `"sensitive model endpoints must use the local kind"`), but `_parse_models` applies no
  such check and `apply_manifest` writes the row with a plain `upsert_model_endpoint`
  ([`boltrig/config/manifest_apply.py:177`](../../../boltrig/config/manifest_apply.py) `"await store.upsert_model_endpoint(endpoint)"`). Two authoring paths, one rule, one
  enforcement point.

- **RISK-1002: the shipped example manifest declares a sensitive endpoint the platform
  route calls ineligible.** `manifest.example.yaml` uses `kind: vllm` for
  `local-sensitive` ([`manifest.example.yaml:73`](../../../manifest.example.yaml) `"kind: vllm"`), while `/v1/model-policy` requires `endpoint.kind == "local"` for
  eligibility ([`boltrig/kernel/platform_routes/model_endpoints.py:86`](../../../boltrig/kernel/platform_routes/model_endpoints.py) `and endpoint.kind == "local"`). A default install therefore reports
  `policy.state = "degraded"` and `sensitive.serving_state = "refuses_sensitive_routing"`
  while the router, which tests only `data_class`, routes to it happily. The operator
  reading the posture and the code enforcing it disagree.

- **RISK-1003: the sensitive-memory guard is a name-set membership test that its own
  constructor satisfies by default.** `self._local_endpoints = local_endpoints or
  {sensitive_endpoint}` ([`boltrig/memory/adapter.py:73`](../../../boltrig/memory/adapter.py) `"self._local_endpoints = local_endpoints or {sensitive_endpoint}"`) and
  `build_memory_adapter` always includes the embedding endpoint in the local set
  ([`boltrig/memory/adapter.py:302`](../../../boltrig/memory/adapter.py) `cfg.get("local_endpoints") or [sensitive, cfg.get("extraction_endpoint", sensitive)]`),
  so the guard can only ever fire when an operator explicitly configures
  `memory.local_endpoints` to a set that excludes `memory.embedding_endpoint`. It never
  reads the endpoint's stored `data_class`. The doctor check at
  [`boltrig/api/doctor.py:486`](../../../boltrig/api/doctor.py) `or endpoints[endpoint_id].data_class != "sensitive"` is the only thing that
  actually ties the memory endpoints to the sensitive class, and it is a static
  pre-deploy check, not a runtime guard.

- **RISK-1004: cost is priced from the capability's declared endpoint, not the model that
  served.** `_true_up_cost` derives the price key from `capability.model_endpoint`
  ([`boltrig/fleet/spawn.py:383`](../../../boltrig/fleet/spawn.py) `"ep = await self._kernel.store.get_model_endpoint(tenant_id, capability.model_endpoint)"`),
  while the served model is separately available in `model_route["model"]` in the same
  caller ([`boltrig/fleet/spawn_completion.py:53`](../../../boltrig/fleet/spawn_completion.py) `"cost_micros = await spawner._true_up_cost("`). On the automatic Codex route the served
  model is `codex_config["model_id"]`, and on the scoped-AI route it is
  `binding.model_id`; neither equals the capability endpoint's `model`. The price table is
  keyed by served model name, which the manifest states explicitly, so those runs silently
  miss their configured rate and fall back to the tier default the manifest itself warns
  "systematically OVER-BILLS" ([`manifest.example.yaml:106`](../../../manifest.example.yaml) `"unpriced deployment therefore systematically OVER-BILLS"`). The FR-COST-04 test
  exercises `price_micros` as a pure function only, never this key derivation.

- **RISK-1005: two model-egress paths never reach the router.** The Cognee knowledge
  compiler ([`boltrig/memory/cognee_model_binding.py:48`](../../../boltrig/memory/cognee_model_binding.py) `"resolution = await resolve_ai_key("`) and the realtime voice profile resolver
  ([`boltrig/kernel/call_profiles.py:39`](../../../boltrig/kernel/call_profiles.py) `"route = resolve_realtime_model_profile(model_id) if model_id else None"`) both send
  tenant content to an external provider without consulting `data_class`,
  `sensitive_endpoint`, or the PII classifier. The architecture doc's "runs inside every
  spawn" is accurate; the AGENTS.md sentence read as "every model call" is not.

- **RISK-1006: the sensitive-endpoint refusal for a MISSING configured role is a
  different exception from the one the doctrine names.** When `sensitive_endpoint_id` is
  set but the row is retired or absent, `_active_endpoint` raises
  `ModelEndpointUnavailable` (409) from inside the sensitive branch rather than
  `SensitiveDataMisrouted` (403)
  ([`boltrig/fleet/model_router.py:111`](../../../boltrig/fleet/model_router.py) `"local = await _active_endpoint("`). Still a refusal, but any caller or alert keyed on
  `sensitive_data_misrouted` will not see it. No test in
  `tests/security/test_sensitive_routing.py` covers this branch (bounded: read the whole
  file, 2026-08-24).

- **RISK-1007: `genesis.sh` starts the gateway profile but never the local profile.**
  `COMPOSE_PROFILES=(--profile gateway)` ([`genesis.sh:28`](../../../genesis.sh) `"COMPOSE_PROFILES=(--profile gateway)"`) while the manifest it copies declares
  `sensitive_endpoint: local-sensitive` at `http://local-model:8000/v1`
  ([`manifest.example.yaml:79`](../../../manifest.example.yaml) `"sensitive_endpoint: local-sensitive"`). The endpoint ROW is active, so the router
  routes and the residency rule is satisfied at the decision layer; the actual call then
  fails at connect time against a service that was never started. Residency is enforced
  by row, not by reachability.

- **RISK-1008: the shipped manifest's endpoint models are empty strings.**
  `${BOLTRIG_DEFAULT_MODEL:-}` and `${BOLTRIG_LOCAL_MODEL:-}` have no default anywhere in
  the tree ([`manifest.example.yaml:69`](../../../manifest.example.yaml) `"model: ${BOLTRIG_DEFAULT_MODEL:-}"`), and `ModelEndpoint` applies no non-empty
  validation to `model`. An empty model is filtered out of chat choices and yields no
  `served_model_route`, but it is accepted into the store and into the price lookup.

- **RISK-1009: `BOLTRIG_BIFROST_MANAGEMENT_KEY` is the only credential on every Bifrost
  ADMIN call and is undocumented.** It appears exactly once in the tree, at its reader
  ([`boltrig/identity/bifrost_user_transport.py:77`](../../../boltrig/identity/bifrost_user_transport.py) `self._management_key = source.get("BOLTRIG_BIFROST_MANAGEMENT_KEY") or ""`), and
  defaults to the empty string, which sends NO `authorization` header on
  provider-creation, key-write and virtual-key-creation calls. It is absent from
  `.env.example`, `docker-compose.yml`, `genesis.sh` and `docs/DEPLOYMENT.md` (bounded:
  `grep -rn "BOLTRIG_BIFROST_MANAGEMENT_KEY"` over the pinned tree).

- **RISK-1010: a sensitive-plus-wrong-kind endpoint upsert consumes a human approval
  before it is refused.** The catalogue preflight returns early for any non-standard row
  ([`boltrig/config/control_model_endpoints.py:99`](../../../boltrig/config/control_model_endpoints.py) `"return"`), so the `kind != "local"` `ControlConflict` fires only at execute, after the
  HITL gate has consumed the approval.

- **RISK-1011: the schema's `kind` comment is stale and the vocabulary is not enforced
  anywhere.** The column comment lists four kinds
  ([`boltrig/store/schema.sql:376`](../../../boltrig/store/schema.sql) `"kind        TEXT NOT NULL,                          -- anthropic | openai | ollama | vllm"`)
  and omits `bifrost` (used throughout) and `local` (required for sensitive rows). There
  is no CHECK constraint and no Python enum; `kind` is a free string whose only tests are
  the three literal comparisons at
  [`boltrig/config/control_model_endpoints.py:178`](../../../boltrig/config/control_model_endpoints.py) `if data_class == "sensitive" and kind != "local":`,
  [`boltrig/kernel/platform_routes/model_endpoints.py:86`](../../../boltrig/kernel/platform_routes/model_endpoints.py) `and endpoint.kind == "local"`
  and [`boltrig/kernel/call_profiles.py:51`](../../../boltrig/kernel/call_profiles.py) `and endpoint.kind.lower() in {"xai", "x.ai", "grok"}`.

- **RISK-1012: the conversation-to-model binding is per process.** `ModelGateway` is an
  in-memory dict constructed per `RuntimeResolver`
  ([`boltrig/fleet/runtime_resolver.py:55`](../../../boltrig/fleet/runtime_resolver.py) `self._bindings = ModelGateway(ttl_seconds=int(cast(int, self._gateway["ttl_seconds"])))`). Two kernel replicas, or a kernel and
  a fleet worker, hold independent tables, so the SEC-47 promise that a conversation stays
  pinned to one model holds per process, not per conversation. No test asserts
  cross-process behaviour (bounded: read `tests/security/test_round_six.py` gateway tests).

- **RISK-1013: `models.default` is dead configuration.** It is parsed, digested into the
  policy generation, and projected as `inactive_no_consumer`, and no code selects an
  endpoint from it (bounded: `rg -n "\.default\b" boltrig/config boltrig/fleet boltrig/kernel`
  finds only the projection sites). An operator who sets it and expects a routing effect
  gets none.

## 12. OPEN QUESTIONS

1. **Is `kind == "local"` or `data_class == "sensitive"` the intended residency
   predicate?** The router uses the latter, the control-plane and the policy projection
   use the former, and the doctor uses the latter plus a host heuristic. Settled by a
   decision record or by making one of the three the single reader; I found no decision
   record naming `kind` (bounded: `rg -ni "local kind|kind == .local" docs/decisions/`
   returns nothing).

2. **Was the Cognee compilation path deliberately excluded from SEC-12?** The distill path
   got its own explicit companion rule ([`tests/invariants.yaml:2793`](../../../tests/invariants.yaml) `"sensitive data can never be laundered into weights served off-box (decision 0023, SEC-12 companion)"`),
   which shows the question was asked at least once. Nothing equivalent exists for
   knowledge compilation. Settled by reading `docs/decisions/` for a knowledge residency
   ruling, or by asking the author.

3. **Does the Bifrost deployment actually require the management bearer?** The transport
   sends no `authorization` header when `BOLTRIG_BIFROST_MANAGEMENT_KEY` is empty, which
   is the default. Whether the pinned `maximhq/bifrost` digest enforces admin auth is a
   property of that image, not of this tree. Settled by reading the pinned image's config
   defaults, which I did not do (no docker in this run).

4. **Is `ModelEndpoint.fallback` ever traversed by anything?** The record calls it "a
   stored reference for an explicit, future health-based failover decision" and the router
   explicitly refuses to follow it. I found only validation and reference-graph readers
   (bounded: `rg -n "\.fallback" boltrig/` returns `config/control_model_endpoints.py`,
   `store/model_endpoints_{memory,postgres}.py`, `store/rows.py`,
   `kernel/platform_routes/model_endpoints.py`). If nothing will ever traverse it, it is a
   DEAD field carrying approval weight; if something will, that is unwritten.

5. **What prices a run whose capability declares no `model_endpoint` at all?**
   `_true_up_cost` leaves `priced_model` as `None` and the tier default applies. Whether
   that is intended for the scoped-AI and automatic-Codex routes, which are the normal
   hosted lanes, is undocumented.

6. **Does any Worker surface show the operator that `default` is inert?** The API says
   `inactive_no_consumer`; whether `apps/worker` renders that string is outside my read
   bound.

## 13. Requirements table

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1000 | A model endpoint is a tenant-scoped record of id, kind, model, base_url, fallback, data_class, is_active, modalities and revision. | IMPLEMENTED | `boltrig/models/libraries.py:194` `"class ModelEndpoint:"` | SEC-WRK-14 |
| BT-REQ-1001 | A model endpoint rejects any modality outside text, vision, stt, tts and realtime. | IMPLEMENTED | `boltrig/models/libraries.py:222` `"invalid = set(values) - set(MODEL_MODALITIES)"` | SEC-WRK-14 |
| BT-REQ-1002 | A model endpoint lowercases, trims and dedupes its modalities and defaults an empty set to text. | IMPLEMENTED | `boltrig/models/libraries.py:225` `object.__setattr__(self, "modalities", values or ("text",))` | SEC-WRK-14 |
| BT-REQ-1003 | A model endpoint revision is a positive integer. | IMPLEMENTED-UNTESTED | `boltrig/models/libraries.py:214` `"model endpoint revision must be a positive integer"` | - |
| BT-REQ-1004 | The cost tier vocabulary is closed to cheap, standard and expensive across manifest and control authoring. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_cost_tier_vocabulary_is_closed_across_manifest_and_control` | FR-COST-04 |
| BT-REQ-1005 | An agent capability folds its legacy text and vision endpoint columns into the generic model_routes map, with the legacy value winning. | IMPLEMENTED | `boltrig/models/libraries.py:131` `routes["text"] = self.model_endpoint` | SEC-WRK-14 |
| BT-REQ-1006 | Capability route authoring requires every named endpoint to exist, be active and advertise its bound modality. | IMPLEMENTED | `boltrig/config/capability_model_routes.py:77` `"if not endpoint.supports(modality):"` | SEC-WRK-14 |
| BT-REQ-1007 | A capability with one text endpoint and no vision route must name a multimodal endpoint. | IMPLEMENTED | `boltrig/config/capability_model_routes.py:88` `"a single agent model must advertise both text and vision modalities"` | SEC-WRK-14 |
| BT-REQ-1008 | The manifest models section parses to endpoints, default, sensitive_endpoint and a per-model price table. | IMPLEMENTED | `boltrig/config/manifest.py:575` `"def _parse_models("` | FR-COST-04 |
| BT-REQ-1009 | Applying a manifest upserts every declared endpoint and installs its price table on the cost accountant. | IMPLEMENTED | `boltrig/config/manifest_apply.py:180` `"cost.set_prices(manifest.models.prices)"` | FR-COST-04 |
| BT-REQ-1010 | A malformed manifest price entry is dropped at parse and the model falls back to its cost tier rather than blocking boot. | IMPLEMENTED | `boltrig/config/manifest.py:591` `"rather than failing load, so a bad price never blocks boot"` | FR-COST-04 |
| BT-REQ-1011 | The manifest endpoint parser applies no sensitive-implies-local check. | IMPLEMENTED-UNTESTED | `boltrig/config/manifest.py:577` `"ModelEndpoint("` | - |
| BT-REQ-1012 | An endpoint id must be one bounded URL-safe path segment and is never normalised. | IMPLEMENTED | `boltrig/model_choice_policy.py:8` `_PATH_SEGMENT = re.compile(r"[A-Za-z0-9._~-]{1,160}\Z")` | SEC-WRK-02 |
| BT-REQ-1013 | An exact model id refuses every mutable alias segment including latest, auto and stable. | IMPLEMENTED | `tests/unit/test_user_model_id_policy.py::test_exact_model_id_still_refuses_mutable_aliases` | SEC-WRK-02 |
| BT-REQ-1014 | A user-connected model id keeps shape and path refusals but accepts the provider's own alias tags. | IMPLEMENTED | `tests/unit/test_user_model_id_policy.py::test_user_model_id_accepts_the_providers_own_alias_tags` | - |
| BT-REQ-1015 | Governed authoring refuses a sensitive endpoint whose kind is not local. | IMPLEMENTED | `boltrig/config/control_model_endpoints.py:178` `if data_class == "sensitive" and kind != "local":` | SEC-12 |
| BT-REQ-1016 | Governed authoring requires an exact immutable model id for a standard bifrost, xai, x.ai or grok endpoint. | IMPLEMENTED | `boltrig/config/control_model_endpoints.py:182` `"model = exact_model_id(model)"` | SEC-12 |
| BT-REQ-1017 | Governed authoring of a standard bifrost endpoint proves the exact model is advertised for its declared modalities. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_bifrost_authoring_requires_live_exact_catalogue_modalities` | SEC-12 |
| BT-REQ-1018 | The catalogue preflight runs before the approval is raised, and only for standard bifrost, xai, x.ai and grok rows. | IMPLEMENTED | `boltrig/config/control_model_endpoints.py:98` `if data_class != "standard" or kind not in` | SEC-12 |
| BT-REQ-1019 | A fallback reference may not be the endpoint itself, must exist, and must be active. | IMPLEMENTED | `boltrig/config/control_model_endpoints.py:25` `"a model endpoint cannot fall back to itself"` | SEC-WRK-14 |
| BT-REQ-1020 | An approved endpoint upsert compare-and-swaps against the approved endpoint, its fallback target and its reference snapshot. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_endpoint_upsert_approval_rebinds_when_a_capability_reference_is_added` | SEC-WRK-14 |
| BT-REQ-1021 | An ordinary replacement upsert preserves the stored is_active flag so a retired endpoint cannot be edited back into service. | IMPLEMENTED | `boltrig/store/model_endpoints_postgres.py:181` `"current.is_active if current else endpoint.is_active,"` | SEC-WRK-14 |
| BT-REQ-1022 | Retire and restore are high-consequence controls bound to the exact endpoint state by compare-and-set. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_endpoint_lifecycle_approval_is_bound_to_the_exact_mutable_state` | SEC-WRK-14 |
| BT-REQ-1023 | Every mutating endpoint operation takes a tenant-scoped advisory lock over the reference graph before reading it. | IMPLEMENTED-UNTESTED | `boltrig/store/model_endpoint_contract.py:19` `"SELECT pg_advisory_xact_lock(hashtextextended($1, 0))"` | SEC-WRK-14 |
| BT-REQ-1024 | Changing a fallback bumps the revision of the old and new fallback targets so their in-flight approvals invalidate. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_approved_fallback_use_and_retirement_compare_and_swap_once` | SEC-WRK-14 |
| BT-REQ-1025 | Model endpoint lifecycle behaves identically on the in-memory and PostgreSQL stores. | IMPLEMENTED | `tests/store/test_store_parity.py::test_model_endpoint_lifecycle_matches_on_both_stores` | SEC-WRK-14 |
| BT-REQ-1026 | The model_endpoints table is tenant-fenced by the row-level-security overlay. | IMPLEMENTED | `boltrig/store/rls.sql:79` `"'workflow_definitions','model_endpoints','work_items','hitl_requests',"` | SEC-08 |
| BT-REQ-1027 | The router selects a capability's endpoint by modality, falling back from vision to the vision override then the primary. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_agent_accepts_multimodal_or_explicit_text_and_vision_routes` | SEC-WRK-14 |
| BT-REQ-1028 | The router resolves exactly one named endpoint reference and never traverses its fallback. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_retirement_preserves_configuration_and_every_reference_fails_closed` | SEC-WRK-14 |
| BT-REQ-1029 | A missing or retired endpoint is audited as model_endpoint_unavailable and refused with a typed 409. | IMPLEMENTED | `boltrig/fleet/model_router.py:164` `status="model_endpoint_unavailable",` | SEC-WRK-14 |
| BT-REQ-1030 | An endpoint that does not advertise the requested modality is audited and refused with a typed 409. | IMPLEMENTED | `boltrig/fleet/model_router.py:95` `"model_endpoint_modality_unavailable",` | SEC-WRK-14 |
| BT-REQ-1031 | Standard-classified data returns its resolved endpoint unconstrained. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_standard_data_uses_its_endpoint` | SEC-12 |
| BT-REQ-1032 | Sensitive-classified data returns the capability's own endpoint when that endpoint is data_class sensitive. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_sensitive_data_routes_to_local_endpoint` | SEC-12 |
| BT-REQ-1033 | Sensitive-classified data on a hosted endpoint is redirected to the configured sensitive endpoint when that endpoint is itself sensitive. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_sensitive_substitutes_configured_local_endpoint` | SEC-12 |
| BT-REQ-1034 | Sensitive-classified data with no reachable sensitive endpoint is audited as sensitive_data_misrouted and refused with a typed 403, never downgraded to a standard provider. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_pii_bearing_payload_without_local_endpoint_fails_closed` | SEC-12 |
| BT-REQ-1035 | A configured sensitive endpoint that is missing or retired raises model_endpoint_unavailable from inside the sensitive branch rather than falling through to a standard endpoint. | IMPLEMENTED-UNTESTED | `boltrig/fleet/model_router.py:111` `"local = await _active_endpoint("` | SEC-12 |
| BT-REQ-1036 | The spawn path enforces the sensitive-to-local rule end to end. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_spawn_blocks_sensitive_on_hosted_capability` | SEC-12 |
| BT-REQ-1037 | The caller's data_class classification is not trusted alone: the deterministic PII scanner over the outbound prompt forces the sensitive route. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_pii_bearing_payload_routes_local_despite_caller_classification` | SEC-12 |
| BT-REQ-1038 | The PII scanner classifies only and never rewrites the outbound payload. | IMPLEMENTED | `boltrig/fleet/model_router.py:46` `"return pii.redact(text).has_pii or pii.contains_identity(text) is not None"` | SEC-13 |
| BT-REQ-1039 | A payload with no pattern hits stays standard and keeps its governed hosted endpoint. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_clean_payload_still_routes_hosted` | SEC-12 |
| BT-REQ-1040 | A user AI configuration naming an external provider cannot move a sensitive call off the local endpoint, and cannot rewrite a standard governed endpoint either. | IMPLEMENTED | `tests/security/test_sensitive_routing.py::test_ai_key_profile_cannot_override_governed_model_endpoint` | SEC-12 |
| BT-REQ-1041 | A caller model choice is refused for a non-Codex capability, a sensitive request or a pinned profile. | IMPLEMENTED | `boltrig/fleet/codex_model_selection.py:45` `capability.runtime != "codex" or sensitive or pinned_policy` | SEC-WRK-02 |
| BT-REQ-1042 | A malformed, blank or oversized model choice id is refused with a typed model_endpoint_unavailable. | IMPLEMENTED | `tests/security/test_chat_model_choices.py::test_chat_rejects_blank_whitespace_and_oversized_choice_ids` | SEC-WRK-02 |
| BT-REQ-1043 | A model choice cannot change while a conversation turn is active. | IMPLEMENTED | `tests/integration/test_chat.py::test_model_choice_on_in_flight_steer_is_rejected_not_silently_reused` | SEC-WRK-02 |
| BT-REQ-1044 | A resolved model choice must be a standard, text-capable endpoint with an exact immutable model id, proven against the live catalogue. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_runtime_refuses_unadvertised_or_unavailable_catalogue_choice` | SEC-WRK-02 |
| BT-REQ-1045 | A vision request whose chosen model lacks catalogue image support is refused. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_runtime_refuses_a_vision_choice_without_catalogue_image_support` | SEC-WRK-02 |
| BT-REQ-1046 | The whole Codex-to-Bifrost endpoint composition is skipped for sensitive-classified requests. | IMPLEMENTED | `boltrig/fleet/runtime_resolver.py:137` `if capability.runtime == "codex" and not sensitive:` | SEC-12 |
| BT-REQ-1047 | The default Codex route uses the composed process model rather than the capability's stored endpoint model. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_default_codex_route_uses_composed_model_not_capability_endpoint` | SEC-WRK-02 |
| BT-REQ-1048 | Automatic Codex routing is refused when no model gateway is configured. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_automatic_codex_route_refuses_without_the_bifrost_gateway` | SEC-WRK-02 |
| BT-REQ-1049 | A composed runtime that cannot honestly satisfy an authored pinned profile refuses rather than serving a different model. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_pinned_codex_profile_refuses_a_different_composed_model` | SEC-WRK-02 |
| BT-REQ-1050 | An unavailable Codex runtime carries no speculative model route. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_unavailable_codex_runtime_carries_no_speculative_model_route` | SEC-WRK-02 |
| BT-REQ-1051 | The recorded served-model route projects model and provider only, never a base URL or credential. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_the_route_never_carries_a_base_url` | SEC-WRK-02 |
| BT-REQ-1052 | Process composition refuses to start when the injected sensitive endpoint id disagrees with the manifest. | IMPLEMENTED-UNTESTED | `boltrig/api/bootstrap.py:440` `"sensitive model routing changed during process composition"` | - |
| BT-REQ-1053 | The startup birth-profile receipt records the sensitive role as absent or configured without disclosing the endpoint id. | IMPLEMENTED | `boltrig/config/birth_profile.py:118` `return "sr_absent_v1", "absent"` | - |
| BT-REQ-1054 | The model gateway binds per conversation, not per run, and keeps a conversation on one model across turns. | IMPLEMENTED | `tests/security/test_round_six.py::test_gateway_binds_per_conversation_not_run` | SEC-47 |
| BT-REQ-1055 | The gateway never re-routes sensitive data and is completely inert when no gateway URL is set. | IMPLEMENTED | `tests/security/test_round_six.py::test_gateway_never_reroutes_sensitive_and_is_inert_when_unset` | SEC-47 |
| BT-REQ-1056 | The conversation binding table is TTL-bounded and size-bounded at 4096 entries, sweeping expired entries before evicting the earliest-expiring live ones. | IMPLEMENTED-UNTESTED | `boltrig/fleet/model_gateway.py:48` `"_MAX_BINDINGS = 4_096"` | SEC-47 |
| BT-REQ-1057 | An explicit server-validated model switch rebinds the conversation's affinity rather than losing to the existing binding. | IMPLEMENTED | `tests/unit/test_runtime_resolver_codex.py::test_explicit_choice_rebinds_same_conversation_a_to_b` | SEC-WRK-02 |
| BT-REQ-1058 | Bifrost is wired into the stack as a profile-gated service on the sandbox network with a loopback admin port, and genesis and dev-up start that profile. | IMPLEMENTED | `tests/security/test_round_six.py::test_bifrost_is_wired_into_the_stack` | FR-GW-01 |
| BT-REQ-1059 | The bifrost and local-model images are pinned to digests. | IMPLEMENTED-UNTESTED | `docker-compose.yml:519` `"image: maximhq/bifrost@sha256:c4de3a1d6bd2f9b8b0b8f508deaaf0337a793603d2b84b61138cdb35f94a4318"` | - |
| BT-REQ-1060 | The secure overlay removes the published host ports of both bifrost and local-model. | IMPLEMENTED-UNTESTED | `deploy/compose.secure.yml:69` `"ports: !override []"` | - |
| BT-REQ-1061 | Readiness reports a configured gateway with no armed probe as unchecked with reason configured_but_health_check_disabled, never as disabled. | IMPLEMENTED | `tests/unit/test_readiness_gateway_posture.py::test_an_explicit_false_health_flag_does_not_arm_a_probe` | - |
| BT-REQ-1062 | Platform status reports the gateway with cache and profile posture only and never a URL, key or token. | IMPLEMENTED | `tests/security/test_platform_status.py::test_model_gateway_status_is_bounded_and_redacted` | FR-GW-03 |
| BT-REQ-1063 | Optional gateway live-health polling is internal-host-only, bounded, and fail-safe. | IMPLEMENTED | `tests/security/test_model_gateway_live_health.py::test_model_gateway_live_health_rejects_external_hosts_without_polling` | FR-GW-04 |
| BT-REQ-1064 | Catalogue discovery calls only the configured internal /v1/models route on a known host with an exact /v1 path. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_bifrost_model_catalogue_rejects_ssrf_and_malformed_gateway_urls` | FR-GW-05 |
| BT-REQ-1065 | Catalogue discovery disables redirects and environment proxies and forces identity content encoding. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_bifrost_model_catalogue_transport_disables_redirects_and_environment_proxies` | FR-GW-05 |
| BT-REQ-1066 | Catalogue discovery bounds body bytes, row count, page count and cursor format, and validates the pinned pagination schema. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_bifrost_model_catalogue_bounds_body_rows_and_schema` | FR-GW-05 |
| BT-REQ-1067 | Catalogue pagination is all-or-nothing: partial pages are never retained. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_bifrost_model_catalogue_pagination_is_bounded_and_all_or_nothing` | FR-GW-05 |
| BT-REQ-1068 | The catalogue cache single-flights concurrent callers, expires on a clamped TTL and fails closed. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_catalogue_cache_singleflights_and_expires_fail_closed` | FR-GW-05 |
| BT-REQ-1069 | Every catalogue failure returns a typed unavailable result with zero models and a reason from a closed ten-value vocabulary. | IMPLEMENTED | `boltrig/fleet/bifrost_model_catalogue.py:81` `return {"status": "unavailable", "models": [], "reason": reason}` | FR-GW-05 |
| BT-REQ-1070 | Catalogue membership matches on the exact model id only: display names, aliases, duplicate rows and malformed snapshots all fail closed. | IMPLEMENTED | `boltrig/model_catalogue_policy.py:70` `"if not matches:"` | SEC-12 |
| BT-REQ-1071 | A store endpoint's declared modalities may stand in for a catalogue row only when that row carries no input_modalities key at all. | IMPLEMENTED | `tests/unit/test_model_catalogue_policy_declared.py::test_bare_row_without_declaration_stays_refused` | - |
| BT-REQ-1072 | A catalogue row carrying a malformed input_modalities key is refused even when the store declares modalities. | IMPLEMENTED | `tests/unit/test_model_catalogue_policy_declared.py::test_malformed_modalities_refuse_even_with_declaration` | - |
| BT-REQ-1073 | A declared vision modality is compared as image, matching the advertised form. | IMPLEMENTED | `tests/unit/test_model_catalogue_policy_declared.py::test_declared_vision_maps_to_image_like_the_advertised_form` | - |
| BT-REQ-1074 | The Bifrost model catalogue route is author-only and re-projects even an injected provider so upstream fields cannot escape. | IMPLEMENTED | `tests/security/test_bifrost_model_catalogue.py::test_bifrost_model_catalogue_route_reprojects_an_injected_provider` | FR-GW-05 |
| BT-REQ-1075 | Chat model choices are filtered to active, standard, text-capable endpoints and expose an opaque choice id, exact model name, modalities and availability reason, never provider topology. | IMPLEMENTED | `tests/security/test_chat_model_choices.py::test_chat_model_choices_are_tenant_scoped_exact_and_catalogue_verified` | SEC-WRK-02 |
| BT-REQ-1076 | A catalogue failure marks every model choice unavailable rather than admitting an unproven one. | IMPLEMENTED | `tests/security/test_chat_model_choices.py::test_catalogue_failure_marks_every_safe_choice_unavailable` | SEC-WRK-02 |
| BT-REQ-1077 | A provider outside the native Bifrost set is bound as an OpenAI-compatible custom provider and requires an explicit base URL. | IMPLEMENTED | `tests/unit/test_bifrost_custom_provider_base_url.py::test_a_new_custom_provider_carries_its_url_in_network_config` | - |
| BT-REQ-1078 | A custom provider's base URL is written to both network_config and custom_provider_config, and is read back from network_config first. | IMPLEMENTED | `tests/unit/test_bifrost_custom_provider_base_url.py::test_the_custom_provider_config_spelling_is_kept_too` | - |
| BT-REQ-1079 | An existing custom provider row bound to a different address is refused rather than silently re-pointed. | IMPLEMENTED | `tests/unit/test_bifrost_custom_provider_base_url.py::test_a_genuinely_different_address_is_still_refused` | - |
| BT-REQ-1080 | A native Bifrost provider is created with no address. | IMPLEMENTED | `tests/unit/test_bifrost_custom_provider_base_url.py::test_a_native_provider_still_sends_no_address` | - |
| BT-REQ-1081 | A self-hosted provider named in the provider-URL table carries its server URL in the provider-specific key block, and a missing or blank URL is refused with an actionable message. | IMPLEMENTED | `tests/unit/test_bifrost_selfhosted_key.py::test_a_missing_url_is_refused_HERE_with_a_usable_message` | - |
| BT-REQ-1082 | A keyed provider does not require a URL and gets no provider-specific block. | IMPLEMENTED | `tests/unit/test_bifrost_selfhosted_key.py::test_a_keyed_provider_does_not_require_a_url` | - |
| BT-REQ-1083 | The Bifrost administration transport accepts only an internal host on an exact /v1 path and refuses redirects, non-identity encodings, oversized bodies and non-object JSON. | IMPLEMENTED-UNTESTED | `boltrig/identity/bifrost_user_transport.py:42` `or parsed.path.rstrip("/") != "/v1"` | - |
| BT-REQ-1084 | A scoped Bifrost binding is derived idempotently from tenant, level, scope and modality and stores only the narrowed virtual key. | IMPLEMENTED | `boltrig/identity/bifrost_user_binding.py:70` `"digest = hashlib.sha256("` | - |
| BT-REQ-1085 | A binding proven unusable is diagnosed as a wrong address or a wrong model name using the gateway's own provider-key status, which is diagnostic only. | IMPLEMENTED-UNTESTED | `boltrig/identity/bifrost_user_binding.py:258` `if status == "list_models_failed":` | - |
| BT-REQ-1086 | Revoking a scoped binding deletes the virtual key then the provider key, tolerating 404 but refusing any other status. | IMPLEMENTED-UNTESTED | `boltrig/identity/bifrost_user_admin.py:208` `"if virtual_status not in {200, 204, 404}:"` | - |
| BT-REQ-1087 | Cost is priced as tokens times micros per token, with a configured per-model rate winning over the cost-tier default. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_model_price_from_config_overrides_tier_default` | FR-COST-04 |
| BT-REQ-1088 | A per-model rate may be a single blended number or the rate card's input and output pair, and a missing leg falls back to the other leg rather than to zero. | IMPLEMENTED | `boltrig/kernel/cost.py:107` `"input_rate = output_rate"` | FR-COST-04 |
| BT-REQ-1089 | A sub-micro per-token price is charged rather than truncated to free. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_a_sub_micro_price_is_not_free` | FR-COST-04 |
| BT-REQ-1090 | Tokens the runtime did not attribute to a leg are billed at the input rate, so a run reporting only a total is never billed as free. | IMPLEMENTED | `boltrig/kernel/cost.py:151` `"return max(0, round("` | FR-COST-04 |
| BT-REQ-1091 | A negative usage report is never a credit: token counts are floored at zero and the priced product is floored at zero. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_a_price_never_becomes_a_credit` | FR-COST-04 |
| BT-REQ-1092 | The pre-run budget estimate is deterministic and always priced at the cost-tier rate with no model. | IMPLEMENTED-UNTESTED | `boltrig/fleet/spawn_budget.py:19` `"return tokens, price_micros(tokens, cost_tier)"` | FR-COST-02 |
| BT-REQ-1093 | The budget ledger is trued up post-run by the signed actual-minus-estimate delta, and a degraded run refunds the whole estimate. | IMPLEMENTED | `tests/security/test_cost_trueup.py::test_budget_trued_up_to_actual_after_run` | FR-COST-03 |
| BT-REQ-1094 | Post-run pricing derives its price key from the capability's declared model endpoint rather than the endpoint that actually served the call. | IMPLEMENTED-UNTESTED | `boltrig/fleet/spawn.py:383` `"ep = await self._kernel.store.get_model_endpoint(tenant_id, capability.model_endpoint)"` | - |
| BT-REQ-1095 | The Codex runtime reports an input and output token split and a non-positive or non-integer leg is recorded as zero. | IMPLEMENTED-UNTESTED | `boltrig/fleet/codex_runtime_support.py:156` `"return value if type(value) is int and value > 0 else 0"` | FR-COST-04 |
| BT-REQ-1096 | The process model-policy projection names the real consumer of each role, marks the default role inactive, and discloses no endpoint topology. | IMPLEMENTED | `tests/security/test_model_endpoint_lifecycle.py::test_process_model_policy_projection_names_real_consumers_without_topology` | SEC-WRK-14 |
| BT-REQ-1097 | The model-policy projection marks a sensitive role eligible only when its endpoint is active, of kind local, and data_class sensitive. | IMPLEMENTED | `boltrig/kernel/platform_routes/model_endpoints.py:86` `and endpoint.kind == "local"` | SEC-WRK-14 |
| BT-REQ-1098 | Static readiness fails when the manifest's sensitive endpoint is not data_class sensitive, and fails when a configured memory endpoint is not local-sensitive. | IMPLEMENTED | `tests/unit/test_doctor.py::test_production_doctor_has_no_failures_for_secure_posture` | SEC-12 |
| BT-REQ-1099 | A distillation corpus may only target a sensitive-classed endpoint, so sensitive runs cannot be laundered into weights served off-box. | IMPLEMENTED | `boltrig/distill/corpus.py:219` `if target_data_class != "sensitive":` | SEC-12 |
