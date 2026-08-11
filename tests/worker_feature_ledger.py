"""Non-HTTP feature-source ledger for the Worker-primary product.

The HTTP route ledger proves that every API route has a deliberate surface.
This companion ledger covers sources of product behaviour that do not create a
route of their own: manifest sections, serving loops, native commands and
internal/legacy seams.

``worker`` means an ordinary lifecycle belongs in Worker. ``operator`` and
``deployment`` are intentional advanced/infrastructure boundaries. ``missing``
is a tracked product gap, and ``not_product`` is code that must not be
advertised as a live Boltrig capability.
"""

from __future__ import annotations

from dataclasses import dataclass

LIFECYCLE_DIMENSIONS = (
    "discover",
    "configure",
    "operate",
    "observe",
    "recover",
)
LIFECYCLE_OWNERS = frozenset({"worker", "operator", "deployment", "missing", "not_product"})


@dataclass(frozen=True)
class FeatureCoverage:
    source: str
    discover: str
    configure: str
    operate: str
    observe: str
    recover: str
    note: str


def _coverage(
    source: str,
    lifecycle: tuple[str, str, str, str, str],
    note: str,
) -> FeatureCoverage:
    return FeatureCoverage(source, *lifecycle, note)


# Every FleetManifest dataclass field is classified here. ``extra`` is the
# container; each accepted extra section is classified separately below.
MANIFEST_FEATURES: dict[str, FeatureCoverage] = {
    "organisation": _coverage(
        "boltrig/config/manifest.py:FleetManifest.organisation",
        ("worker", "operator", "worker", "worker", "operator"),
        "Worker shows the server-derived organisation; founding/rename recovery is governed administration.",
    ),
    "tenant_id": _coverage(
        "boltrig/config/manifest.py:FleetManifest.tenant_id",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Tenant identity is immutable deployment data, not an editable client field.",
    ),
    "locale_default": _coverage(
        "boltrig/config/manifest.py:FleetManifest.locale_default",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "The tenant default now supplies the effective caller preference until that user overrides it.",
    ),
    "timezone_default": _coverage(
        "boltrig/config/manifest.py:FleetManifest.timezone_default",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "The tenant default now supplies the effective caller preference until override; workflow schedules remain explicit.",
    ),
    "identity": _coverage(
        "boltrig/config/manifest.py:IdentityConfig",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Login/role mapping is visible, while IdP trust material and redirect composition remain deployment-owned.",
    ),
    "models": _coverage(
        "boltrig/config/manifest.py:ModelsConfig",
        ("worker", "missing", "worker", "worker", "missing"),
        "Endpoints are managed in Worker; process-start sensitive routing and price policy are projected, while mutation/rollback and the parsed-only default role remain incomplete.",
    ),
    "hierarchy": _coverage(
        "boltrig/config/manifest.py:HierarchyConfig",
        ("worker", "worker", "worker", "worker", "deployment"),
        "Typed desired/startup-observed state plus lazy pinned permanent reasoning; restart and liveness recovery remain deployment work.",
    ),
    "ephemeral_runtimes": _coverage(
        "boltrig/config/manifest.py:FleetManifest.ephemeral_runtimes",
        ("worker", "worker", "worker", "worker", "worker"),
        "Governed agent profiles are the Worker lifecycle; Codex is the only target runtime.",
    ),
    "spawn_rules": _coverage(
        "boltrig/config/spawn_rules.py",
        ("worker", "missing", "worker", "worker", "operator"),
        "Worker inventories the effective revision, analyzes reachable conflicts and offers preview-only simulation; trusted classification and governed authoring remain incomplete.",
    ),
    "adapters": _coverage(
        "boltrig/config/manifest.py:AdapterConfig",
        ("worker", "worker", "worker", "worker", "worker"),
        "Build and Integrations own the governed adapter lifecycle; provider certification remains explicit.",
    ),
    "hitl": _coverage(
        "boltrig/config/manifest.py:HitlConfig",
        ("worker", "missing", "worker", "worker", "missing"),
        "Inbox, process-start blocking/timeout evidence and bounded janitor attempts work; routing fields are explicitly inactive and policy mutation remains missing.",
    ),
    "development_posture": _coverage(
        "boltrig/config/manifest.py:FleetManifest.development_posture",
        ("operator", "deployment", "operator", "worker", "deployment"),
        "A declared development posture lifts the four-eyes INDEPENDENCE limb on control.* "
        "and nothing else ([2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001). It is never a "
        "Worker affordance: the party it un-constrains is the one who would be clicking, so "
        "it is declared in the tenant manifest at deploy time and cleared the same way. "
        "Observe is `worker` deliberately - every reliance writes a SecurityWriter row, and a "
        "party who was never asked to approve must be able to read afterwards what was done "
        "on their tenant, which is the whole point of that record.",
    ),
    "network": _coverage(
        "boltrig/config/manifest.py:NetworkConfig",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Worker projects the redacted live web-fetch snapshot and explicit separate-surface gaps; configuration and restart remain deployment-owned.",
    ),
    "privacy": _coverage(
        "boltrig/config/manifest.py:PrivacyConfig",
        ("worker", "operator", "worker", "worker", "missing"),
        "Worker projects exact partial coverage; redaction, residency, complete erasure and compliance export remain product gaps.",
    ),
    "chat": _coverage(
        "boltrig/config/manifest.py:ChatConfig",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Worker uses the live chat limits and continuity contract; low-level process tuning stays deployment-owned.",
    ),
    "extra": _coverage(
        "boltrig/config/manifest.py:FleetManifest.extra",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Container only; accepted sections are classified individually.",
    ),
}


# A covered parent section must not hide an inert nested policy field. These
# declarations include the dataclasses embedded by identity, model and
# spawn-rule sections as well as the records declared in manifest.py.
NESTED_MANIFEST_FIELDS: dict[str, FeatureCoverage] = {}


def _nested(
    record: str,
    fields: str,
    source: str,
    lifecycle: tuple[str, str, str, str, str],
    note: str,
) -> None:
    for field_name in fields.split():
        key = f"{record}.{field_name}"
        if key in NESTED_MANIFEST_FIELDS:
            raise ValueError(f"duplicate nested manifest field: {key}")
        NESTED_MANIFEST_FIELDS[key] = _coverage(f"{source}:{key}", lifecycle, note)


_nested(
    "CredentialRef",
    "id ref kind",
    "boltrig/config/manifest.py",
    ("operator", "operator", "worker", "operator", "operator"),
    "Credential references are advanced opaque data; ordinary setup uses sealed provider forms.",
)
_nested(
    "CredentialRef",
    "store",
    "boltrig/config/manifest.py",
    ("operator", "deployment", "worker", "operator", "deployment"),
    "Secret-store selection is deployment policy and never a browser secret path.",
)
_nested(
    "IdentityConfig",
    "provider",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "Effective login posture is visible; IdP selection remains deployment-owned.",
)
_nested(
    "IdentityConfig",
    "issuer audience jwks_uri",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "A complete manifest OIDC trio selects generic OIDC trust; concurrent process trust must match exactly or boot refuses, and Worker projects only configured/serving state.",
)
_nested(
    "IdentityConfig",
    "metadata_url",
    "boltrig/config/manifest.py",
    ("not_product", "not_product", "not_product", "not_product", "not_product"),
    "SAML metadata residue is unused while the manifest loader rejects SAML.",
)
_nested(
    "IdentityConfig",
    "role_mappings",
    "boltrig/config/manifest.py",
    ("operator", "operator", "worker", "worker", "operator"),
    "Mappings govern grants, while raw trust-policy authoring and rollback remain server-owned and unavailable in the Worker.",
)
_nested(
    "ModelsConfig",
    "endpoints",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Worker owns the governed model-endpoint lifecycle.",
)
_nested(
    "ModelsConfig",
    "default",
    "boltrig/config/manifest.py",
    ("worker", "missing", "not_product", "worker", "deployment"),
    "Worker projects this parsed role as inactive because no serving path consumes it.",
)
_nested(
    "ModelsConfig",
    "sensitive_endpoint prices",
    "boltrig/config/manifest.py",
    ("worker", "missing", "worker", "worker", "missing"),
    "Worker projects process-start routing/billing policy and current endpoint validity; governed mutation and rollback remain missing.",
)
_nested(
    "BudgetConfig",
    "token_limit cost_limit_micros hard_stop",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Worker projects these fields through the governed budget lifecycle.",
)
_nested(
    "BudgetConfig",
    "window",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Worker exposes exact per-run isolation and UTC daily/monthly usage evidence; calendar windows roll automatically and current calendar buckets support governed reset.",
)
_nested(
    "HierarchyTier",
    "name supported_skills department budget",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "deployment"),
    "These desired permanent-fleet fields reach the explicit manifest-apply/redeploy boundary.",
)
_nested(
    "HierarchyTier",
    "runtime model_endpoint max_depth cost_tier purpose brief",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "deployment"),
    "These fields construct lazy, pinned, metered permanent profiles after restart; unavailable admission falls back deterministically and production Codex remains gated.",
)
_nested(
    "HierarchyConfig",
    "tier1 tier2",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "deployment"),
    "Desired hierarchy is separate from startup-observed runtime evidence.",
)
_nested(
    "EphemeralRuntime",
    "name runtime supported_skills max_depth cost_tier model_endpoint",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Worker owns the governed Codex target-profile lifecycle. Existing non-Codex "
    "compatibility rows remain visible and can be preserved during migration, but "
    "new Worker profile authoring offers only Codex.",
)
_nested(
    "AdapterConfig",
    "id credential",
    "boltrig/config/manifest.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Build and Integrations own identity and sealed credential setup.",
)
_nested(
    "AdapterConfig",
    "runtime module_ref",
    "boltrig/config/manifest.py",
    ("operator", "operator", "worker", "operator", "deployment"),
    "Arbitrary runtime and Python module wiring remains advanced reviewed configuration.",
)
_nested(
    "AdapterConfig",
    "version source",
    "boltrig/config/manifest.py",
    ("worker", "operator", "worker", "worker", "deployment"),
    "Effective package provenance is visible; rollout remains deployment-owned.",
)
_nested(
    "HitlConfig",
    "primary_channel notify_via escalation_chain",
    "boltrig/config/manifest.py",
    ("worker", "missing", "not_product", "worker", "missing"),
    "Worker projects these fields as inactive because they have no serving notification or escalation consumer.",
)
_nested(
    "HitlConfig",
    "approval_timeout_seconds blocking_verbs",
    "boltrig/config/manifest.py",
    ("worker", "missing", "worker", "worker", "operator"),
    "Worker projects the exact process-start policy and janitor attempts; governed mutation remains absent.",
)
_nested(
    "NetworkConfig",
    "air_gapped https_proxy allowed_domains blocked_domains",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "Worker projects exact redacted web-fetch enforcement plus browser, MCP, adapter and provider coverage boundaries.",
)
_nested(
    "NetworkConfig",
    "ca_bundle",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "The bundle is applied to direct and proxied web-fetch TLS; Worker exposes only configured/enforced state.",
)
_nested(
    "PrivacyConfig",
    "pii_redaction data_residency redact_fields",
    "boltrig/config/manifest.py",
    ("worker", "operator", "not_product", "worker", "missing"),
    "Worker projects these rules as inactive because they do not govern every model, adapter, store and derived-data boundary.",
)
_nested(
    "PrivacyConfig",
    "retention_days",
    "boltrig/config/manifest.py",
    ("worker", "operator", "worker", "worker", "operator"),
    "Worker projects closed-conversation-only coverage and bounded janitor attempts.",
)
_nested(
    "ChatConfig",
    "default_capability skills_by_role default_skills max_attachments max_attachment_bytes max_total_attachment_bytes compaction_threshold compaction_keep_recent",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "The live chat admission and continuity paths consume these bounded policies.",
)
_nested(
    "ChatConfig",
    "continuity_tool_name_chars continuity_tool_pairs_per_turn",
    "boltrig/config/manifest.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "The two bounds on what a prior turn's tool work may say inside a later prompt "
    "([2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001 D2). Tighten-only, so a manifest may "
    "narrow what reaches a model and can never widen it.",
)
_nested(
    "ChatConfig",
    "heartbeat_seconds conversation_page_size conversation_max_page_size",
    "boltrig/config/manifest.py",
    ("operator", "deployment", "worker", "worker", "deployment"),
    "These are server-enforced operational tuning fields, not ordinary mutation controls.",
)
_nested(
    "RoleMapping",
    "tenant_id idp_group scope",
    "boltrig/models/identity.py",
    ("operator", "operator", "worker", "operator", "operator"),
    "These fields are advanced identity trust-policy data.",
)
_nested(
    "RoleMapping",
    "role",
    "boltrig/models/identity.py",
    ("operator", "operator", "worker", "worker", "operator"),
    "This field determines the mapped platform-role grant ceiling.",
)
_nested(
    "ModelEndpoint",
    "id kind model base_url data_class is_active",
    "boltrig/models/libraries.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Worker owns the governed endpoint authoring and lifecycle fields.",
)
_nested(
    "ModelEndpoint",
    "modalities",
    "boltrig/models/libraries.py",
    ("worker", "worker", "worker", "worker", "worker"),
    "Which modalities an endpoint serves; authored alongside the other endpoint "
    "fields in the Worker's model-endpoint surface and read by runtime resolution "
    "when routing a turn that needs vision.",
)
_nested(
    "ModelEndpoint",
    "tenant_id",
    "boltrig/models/libraries.py",
    ("worker", "deployment", "worker", "worker", "deployment"),
    "Tenant binding is server-derived and not a client-editable field.",
)
_nested(
    "ModelEndpoint",
    "fallback",
    "boltrig/models/libraries.py",
    ("worker", "worker", "not_product", "worker", "worker"),
    "This is a stored reference only; the router deliberately never traverses it silently.",
)
_nested(
    "SpawnRule",
    "name priority intent_tags capability skills max_depth",
    "boltrig/config/spawn_rules.py",
    ("worker", "missing", "worker", "worker", "operator"),
    "Worker inventories every closed field and previews exact matching without executing; authoring remains unavailable pending a trusted classification source.",
)


MANIFEST_EXTRA_FEATURES: dict[str, FeatureCoverage] = {
    "evaluation": _coverage(
        "manifest extra:evaluation",
        ("worker", "worker", "worker", "worker", "worker"),
        "Worker owns scoped evaluation fixtures and run history.",
    ),
    "notifications": _coverage(
        "manifest extra:notifications",
        ("worker", "worker", "worker", "worker", "worker"),
        "Worker owns the persisted preference/test lifecycle for events Boltrig actually produces.",
    ),
    "personal_agents": _coverage(
        "manifest extra:personal_agents",
        ("worker", "worker", "worker", "worker", "worker"),
        "Account owns the personal-agent lifecycle.",
    ),
    "memory": _coverage(
        "manifest extra:memory",
        ("worker", "worker", "worker", "worker", "worker"),
        "Worker owns facts, recall, feedback and ingestion; projection retry posture is classified below.",
    ),
    "knowledge": _coverage(
        "manifest extra:knowledge",
        ("worker", "worker", "worker", "worker", "worker"),
        "Worker owns canonical source and bundled Cognee projection lifecycles; unavailable external projections are classified as a strategic gap below.",
    ),
    "runtimes": _coverage(
        "manifest extra:runtimes",
        ("worker", "operator", "worker", "worker", "deployment"),
        "Worker exposes approved model profiles/posture; gateway process configuration remains deployment-owned.",
    ),
    "mcp": _coverage(
        "manifest extra:mcp",
        ("worker", "worker", "worker", "worker", "worker"),
        "Build owns explicit governed probe, activate/deactivate and retire/restore operations with bounded durable probe receipts, last-known tool snapshots and exact approval replay.",
    ),
    "chat": _coverage(
        "manifest extra:chat",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "The raw compatibility view feeds memory and runtime consumers; the typed ChatConfig owns ordinary chat policy.",
    ),
    "stack": _coverage(
        "manifest extra:stack",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Operate shows redacted component posture; binaries and service topology are deployment data.",
    ),
    "mastra": _coverage(
        "manifest extra:mastra",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Internal legacy compiler input with no governed production entry; do not advertise it in Worker.",
    ),
    "rivet_agentos": _coverage(
        "manifest extra:rivet_agentos",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Legacy runtime residue behind an explicit disabled gate; Codex is the target runtime.",
    ),
    "browser_cli": _coverage(
        "manifest extra:browser_cli",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Browser actions are governed capabilities; binary/profile policy remains deployment-owned.",
    ),
    "langfuse": _coverage(
        "manifest extra:langfuse",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Worker shows content-free API-process attempt counters; sink health, delivery lag and complete fleet/Hatchet coverage remain deployment evidence.",
    ),
    "reconcile": _coverage(
        "manifest extra:reconcile",
        ("operator", "operator", "deployment", "operator", "operator"),
        "Manifest mass-deactivation policy is advanced config/apply/rollback authority.",
    ),
    "distill": _coverage(
        "manifest extra:distill",
        ("worker", "operator", "worker", "worker", "deployment"),
        "Sleep distillation (decision 0023): gate/promotion receipts and corpus "
        "composition surface as ordinary audit rows; the section itself (base "
        "pin, sidecar/serve URLs) is operator config, and the native trainer "
        "sidecar is deployment topology.",
    ),
}


BACKGROUND_FEATURES: dict[str, FeatureCoverage] = {
    "delegation-pump": _coverage(
        "boltrig/fleet/pump.py:WorkPump.run_forever",
        ("worker", "worker", "worker", "worker", "worker"),
        "Work and Runs expose the ordinary lifecycle; low-level leases remain deployment evidence.",
    ),
    "audit-anchor-janitor": _coverage(
        "boltrig/fleet/anchor.py:run_anchor_forever",
        ("worker", "deployment", "deployment", "worker", "operator"),
        "Anchor evidence is visible; interval/manual forcing stays operational.",
    ),
    "hitl-expiry-janitor": _coverage(
        "boltrig/kernel/hitl_expiry.py:run_hitl_expiry_forever",
        ("worker", "deployment", "worker", "worker", "operator"),
        "Operate shows bounded per-process attempt/success/failure/lag receipts without claiming liveness or complete replica coverage.",
    ),
    "session-distillation": _coverage(
        "boltrig/memory/session_distillation.py:run_distillation_forever",
        ("worker", "operator", "worker", "worker", "operator"),
        "Idle-thread distillation into memory runs in the worker under a memory.remember-only seat; the manifest toggle and idle window stay operational.",
    ),
    "retention-janitor": _coverage(
        "boltrig/fleet/retention.py:run_retention_forever",
        ("worker", "operator", "worker", "worker", "operator"),
        "Closed-conversation erasure runs and Operate shows bounded attempt evidence; interval/manual recovery stays operational.",
    ),
    "workflow-scheduler": _coverage(
        "boltrig/workflows/scheduler_loop.py:run_workflow_scheduler_forever",
        ("worker", "worker", "worker", "worker", "worker"),
        "Desired/observed schedule state, bounded safe occurrence receipts and exact approved terminal retry are live. Infrastructure task exceptions remain visibly pending_or_unknown because terminal Hatchet status reconciliation is unavailable; historical backfill is also explicitly unavailable because it cannot reuse the canonical observed-occurrence claim safely.",
    ),
    "fleet-stack-tool-heartbeat": _coverage(
        "boltrig/fleet/stack_tool_health.py:run_fleet_tool_heartbeat",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Operate consumes the redacted short-lived receipt.",
    ),
    "adapter-health-refresh": _coverage(
        "boltrig/adapters/loader.py:refresh_health",
        ("worker", "worker", "worker", "worker", "worker"),
        "Build shows cached adapter health; external certification is separate.",
    ),
    "memory-projection-delivery": _coverage(
        "boltrig/memory/projection_queue.py",
        ("worker", "worker", "worker", "worker", "missing"),
        "Operate now shows bounded, opaque delivery receipts with receipt age, first-attempt wait, capped automatic attempts and poison-terminal state. They do not prove queue depth or worker liveness. Governed manual replay remains unavailable because the original projection payload is executor-owned and is not retained in the receipt.",
    ),
    "channel-gateway-reconciliation": _coverage(
        "services/channel_gateway/app.py",
        ("worker", "worker", "worker", "worker", "deployment"),
        "Desired/observed socket state, durable per-channel single-owner election, safe Worker lease evidence, show-once scoped token issue and mounted-file hot recovery are live. Token-file placement, multi-replica routing to the process-local MCP token registry and real provider failover acceptance remain deployment-owned; no autonomous workload identity is claimed.",
    ),
    "channel-outbox-delivery": _coverage(
        "boltrig/store/channel_outbox.py",
        ("worker", "worker", "worker", "worker", "worker"),
        "Channels exposes bounded safe receipts and one exact-snapshot governed retry for a terminal failure.",
    ),
    "redis-chat-relay": _coverage(
        "boltrig/kernel/redis_event_relay.py",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Chat reconnect uses it; Redis durability/scale-out acceptance remains deployment evidence.",
    ),
    "backup-sidecar": _coverage(
        "scripts/backup-healthcheck.sh",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Worker reads only a safe shared success marker; off-box, encryption and restore-drill posture remain unknown and deployment-owned.",
    ),
    "password-reset-notifier": _coverage(
        "boltrig/api/auth_recovery_routes.py",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Worker exposes redacted notifier readiness and bounded author/admin attempt evidence; a reviewed production provider, credentials and provider delivery acceptance remain deployment-owned.",
    ),
    "budget-prealert": _coverage(
        "boltrig/kernel/cost.py alert callback",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "An uncomposed callback seam; hard stops work, but pre-alerts must not be advertised.",
    ),
    "addon-birth-profile": _coverage(
        "boltrig/config/birth_profile.py",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Operate compares every retained API/fleet/Hatchet startup receipt with the latest API startup reference; bounded expiry is not liveness or complete replica coverage.",
    ),
    "codex-cell-supervisor": _coverage(
        "boltrig/fleet/infrastructure/codex_cell_supervisor.py",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Operate projects the immutable OFF rollout wall and unavailable durable cell evidence; native admission/canary/preflight remains OFF and deployment-gated.",
    ),
}


NATIVE_COMMANDS: dict[str, FeatureCoverage] = {
    "complete_device_enrollment": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Exact-code device enrollment.",
    ),
    "clear_device_session": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Native device sign-out/recovery.",
    ),
    "device_agent_status": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Native device state projection.",
    ),
    "bind_device_root": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "User-chosen opaque root binding.",
    ),
    "unbind_device_root": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Opaque root revocation.",
    ),
    "stage_device_write": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Digest-bound write staging.",
    ),
    "take_device_read_result": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Lease-bound local read result retrieval.",
    ),
    "materialize_artifact": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "User-selected artifact save.",
    ),
    "open_materialized_artifact": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Opaque-handle artifact open.",
    ),
    "reveal_materialized_artifact": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "worker", "worker", "worker", "worker"),
        "Opaque-handle artifact reveal.",
    ),
    "desktop_update_readiness": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "deployment", "worker", "worker", "worker"),
        "Projects only safe build-time signed-release trust readiness.",
    ),
    "check_desktop_update": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "deployment", "worker", "worker", "worker"),
        "Checks only the binary-pinned HTTPS endpoint with its compiled public key.",
    ),
    "install_desktop_update": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "deployment", "worker", "worker", "worker"),
        "Installs only the exact natively retained checked release after signature verification.",
    ),
    "restart_desktop_after_update": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "deployment", "worker", "worker", "worker"),
        "Requests native restart only after the native installer reports success.",
    ),
    "desktop_oauth_return_readiness": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("worker", "deployment", "missing", "worker", "worker"),
        "Projects native return registration while provider exchange remains unavailable.",
    ),
    "arm_desktop_oauth_return": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "A bounded native primitive exists, but no production Worker callsite or kernel-issued OAuth state contract exists yet.",
    ),
    "take_desktop_oauth_return": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "A one-take native primitive exists, but no production Worker callsite or kernel callback/exchange result contract exists yet.",
    ),
    "cancel_desktop_oauth_return": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "A bounded cancellation primitive exists, but it is unreachable from production Worker until the OAuth lifecycle contract exists.",
    ),
    "camera_discover": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "The read-only USB/AVFoundation probe whose bounded JSON result "
        "boltrig/camera/discovery.py turns into a capability map. It never "
        "captures, writes controls, opens HID or loads vendor code. No production "
        "Worker callsite yet.",
    ),
    "camera_status": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "Reports whether the native layer can see the camera at all, separately "
        "from what the descriptors claim. No production Worker callsite yet.",
    ),
    "camera_validate_lease": _coverage(
        "apps/worker/src-tauri/src/lib.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "Checks a kernel-issued camera lease before any operation that touches "
        "hardware, so exclusive UVC access cannot be taken on the device agent's "
        "say-so. No production Worker callsite yet.",
    ),
    "camera_verify_snapshot": _coverage(
        "apps/worker/src-tauri/src/camera_protocol.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "A read-only native capture probe: it takes one frame, proves decode, and "
        "discards it, which is what promotes snapshot from ADVERTISED to PROVEN. "
        "No production Worker callsite yet - CameraDiscoverySettings reads the "
        "discovery result rather than driving the probe.",
    ),
    "camera_verify_ptz": _coverage(
        "apps/worker/src-tauri/src/camera_protocol.rs",
        ("missing", "missing", "missing", "missing", "missing"),
        "The physical pan/tilt proof behind the PROVEN state for those axes. Native "
        "primitive only; no production Worker callsite yet, and it stays lease-gated "
        "because it moves hardware.",
    ),
}


NATIVE_PLUGIN_FEATURES: dict[str, FeatureCoverage] = {
    "single_instance": _coverage(
        "apps/worker/src-tauri/src/lib.rs:tauri_plugin_single_instance",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "A second desktop launch focuses the existing Worker window; packaged cross-platform focus and deep-link handoff remain release acceptance.",
    ),
    "deep_link": _coverage(
        "apps/worker/src-tauri/src/lib.rs:tauri_plugin_deep_link",
        ("worker", "deployment", "missing", "worker", "deployment"),
        "Strict state-bound custom-scheme parsing and unavailable-state UI exist; kernel callback/exchange and packaged scheme acceptance remain open.",
    ),
    "dialog": _coverage(
        "apps/worker/src-tauri/src/lib.rs:tauri_plugin_dialog",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Native commands own folder and save dialogs and honour cancellation; direct dialog IPC is denied to the main webview and packaged OS acceptance remains open.",
    ),
    "opener": _coverage(
        "apps/worker/src-tauri/src/lib.rs:tauri_plugin_opener",
        ("worker", "deployment", "worker", "worker", "deployment"),
        "Only process-local opaque artifact handles reach native open/reveal; packaged OS association and reveal acceptance remain open.",
    ),
    "updater": _coverage(
        "apps/worker/src-tauri/src/lib.rs:tauri_plugin_updater",
        ("worker", "deployment", "worker", "worker", "worker"),
        "Signed build-time release trust, check/download/verify/install/restart UX and explicit browser or unconfigured-build refusal are complete; packaged cross-platform acceptance remains a release gate.",
    ),
}


CLI_COMMAND_FEATURES: dict[str, FeatureCoverage] = {
    "serve": _coverage(
        "boltrig/api/cli.py:serve",
        ("deployment", "deployment", "deployment", "deployment", "deployment"),
        "Kernel process launch is deployment orchestration, not an in-app action.",
    ),
    "worker": _coverage(
        "boltrig/api/cli.py:worker",
        ("deployment", "deployment", "deployment", "worker", "deployment"),
        "Fleet process launch stays deployment-owned; Worker may project bounded health.",
    ),
    "fleet-health": _coverage(
        "boltrig/api/cli.py:fleet-health",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "The signed short-lived tool receipt is projected in Operate; probe execution stays operational.",
    ),
    "audit-verify": _coverage(
        "boltrig/api/cli.py:audit-verify",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Re-deriving the tamper-evidence chain is an operational probe; the verdict is projected in Operate.",
    ),
    "initiate": _coverage(
        "boltrig/api/cli.py:initiate",
        ("deployment", "deployment", "deployment", "worker", "deployment"),
        "Founding-owner bootstrap is a one-time box-level ceremony; ordinary membership continues in Worker.",
    ),
    "set-password": _coverage(
        "boltrig/api/cli.py:set-password",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Box-level account recovery is retained; ordinary change/reset flows are present in Worker.",
    ),
    "mint-token": _coverage(
        "boltrig/api/cli.py:mint-token",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "The box-level twin is operational; ordinary scoped token lifecycle is present in Worker.",
    ),
    "config-validate": _coverage(
        "boltrig/api/cli.py:config-validate",
        ("deployment", "deployment", "deployment", "deployment", "deployment"),
        "Manifest pre-flight against the candidate image (task #59) is a deploy-recipe step; nothing about it belongs in Worker.",
    ),
    "smoke": _coverage(
        "boltrig/api/cli.py:smoke",
        ("deployment", "deployment", "deployment", "deployment", "deployment"),
        "Offline smoke acceptance is a release/deployment gate.",
    ),
    "check-invariants": _coverage(
        "boltrig/api/cli.py:check-invariants",
        ("deployment", "deployment", "deployment", "deployment", "deployment"),
        "Invariant binding is a repository and release gate, not an ordinary product action.",
    ),
    "chat": _coverage(
        "boltrig/api/cli.py:chat",
        ("worker", "worker", "worker", "worker", "worker"),
        "Terminal Chat is a thin alternate client of the same kernel and gateway contracts.",
    ),
    "opencode-plugin": _coverage(
        "boltrig/api/cli.py:opencode-plugin",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Retained external-client compatibility must not be presented as a target agent runtime.",
    ),
    "install": _coverage(
        "boltrig/api/cli.py:opencode-plugin install",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Nested OpenCode installation is retained compatibility, not a Worker lifecycle.",
    ),
    "doctor": _coverage(
        "boltrig/api/cli.py:doctor",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Operate overlaps the redacted runtime posture; static manifest/env inspection remains deployment-owned.",
    ),
    "version": _coverage(
        "boltrig/api/cli.py:version",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Settings exposes the packaged Worker version in browser and desktop builds; CLI output remains an operational equivalent.",
    ),
}


GOVERNED_WORKER_CONTROL_FEATURES: dict[str, FeatureCoverage] = {}


def _governed_controls(
    sources: str,
    lifecycle: tuple[str, str, str, str, str],
    note: str,
) -> None:
    for source in sources.split():
        if source in GOVERNED_WORKER_CONTROL_FEATURES:
            raise ValueError(f"duplicate governed Worker control source: {source}")
        GOVERNED_WORKER_CONTROL_FEATURES[source] = _coverage(
            f"apps/worker/src/components/{source}",
            lifecycle,
            note,
        )


_governed_controls(
    (
        "build/CapabilityRunner.tsx "
        "ExactApprovalFinalizer.tsx AccountAutomationSections.tsx "
        "OrganisationDirectorySections.tsx OrganisationWorkspaceSections.tsx "
        "OperationsView.tsx AgentProfileEditor.tsx PermanentFleetTopology.tsx "
        "build/ModelEndpointsBuild.tsx build/RegistryBuild.tsx "
        "build/SkillsBuild.tsx ParityViews.tsx "
        "knowledge/KnowledgeView.tsx knowledge/RemembersTab.tsx"
    ),
    ("worker", "worker", "worker", "worker", "worker"),
    "These non-secret controls retain only exact typed route inputs plus an internal approval id, query caller-owned state, replay the same SDK method and invalidate edits, selection changes and refreshes.",
)
_governed_controls(
    "ChatView.tsx chat/WorkDisclosure.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "The chat surface renders HITL requests raised BY a turn: it shows the question and the options the kernel supplied, and replays the operator's decision through the same respondHitl method. It composes no approval of its own, retains only the request id, and settles nothing locally - a decision that never reaches the kernel leaves the turn parked, which is the correct failure.",
)
_governed_controls(
    "settings/CompactSections.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Settings rows that mutate governed configuration surface the kernel's pending_human receipt rather than reporting success: the row keeps its prior value until the change is approved, so a person cannot read a queued change as a made one. It retains no request body beyond the exact typed inputs it sent.",
)
_governed_controls(
    "settings/OvernightSection.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Read-only. The screen reports that a night is parked awaiting a person by finding a pending distill request, and names the Inbox as where that decision is taken; it issues no approval, retains no request body and can settle nothing itself.",
)
_governed_controls(
    "LocalDeviceActions.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Exact pending inputs, staged writes and recovered read bytes remain renderer-memory-only across React remounts; the owner-scoped bounded lease projection recovers durable status and safe receipt summaries. A renderer reload loses pending intent and JS-held bytes, while a native-process restart loses unread native buffers; neither is upgraded into durable authority.",
)
_governed_controls(
    "build/McpServersBuild.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "External MCP probe, activate/deactivate, retire/restore, full inactive configuration replacement and available-action-gated deletion controls replay exact approved server snapshots and route bodies; replacement never reconstructs redacted endpoint or credential data and explicitly requires re-probe after evidence invalidation.",
)
_governed_controls(
    "build/AdaptersBuild.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Ordinary adapter activate, deactivate and delete retain the exact action, route body and requester-visible adapter snapshot, inspect caller-owned approval state and replay the same SDK method. Form, selection and canonical inventory changes invalidate stale intent.",
)
_governed_controls(
    "IntegrationsView.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Integration revocation retains only the exact safe connection snapshot and internal approval id, then replays the same SDK delete after caller-owned approval. Manual-secret setup stays on its separate low-consequence write-only lane and secret values never enter approval state.",
)
_governed_controls(
    "AiKeyManagement.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "AI-key set uses a purpose-built requester-bound opaque proposal that envelope-seals and clears plaintext before approval, recovers safe status after navigation, consumes once and removes staging; non-secret delete uses the shared exact finalizer.",
)
_governed_controls(
    "AutomationView.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Workflow save, schedule, lifecycle, queue, execute and non-secret trigger mutations retain exact typed route inputs and use caller-owned same-method replay. Occurrence retry remains snapshot-bound, while webhook create/rotate keeps its purpose-built one-time-secret finalization.",
)
_governed_controls(
    "ChannelsView.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Connect, configure, disconnect, direct bind, unbind and test-send retain exact typed inputs and replay through caller-owned approval state. Initial/default and per-thread targets use the scoped backend catalogue; self-onboarding is Member-only and department-scope bounded. Delivery retry remains snapshot-bound; pairing uses a requester-owned purpose-specific finalizer that creates and returns its one-time code only after approval.",
)
_governed_controls(
    "EvaluationsView.tsx",
    ("worker", "worker", "worker", "worker", "worker"),
    "Evaluation fixture save and lifecycle changes retain exact typed route inputs and use caller-owned same-method replay. Evaluation execution remains one canonical run lane; Worker does not invent a second resume path.",
)


STRATEGIC_RUNTIME_FEATURES: dict[str, FeatureCoverage] = {
    "codex-native-collaboration": _coverage(
        "boltrig/fleet/infrastructure/codex_runtime_admission.py",
        ("worker", "missing", "missing", "worker", "missing"),
        "Operate exposes the execution-neutral OFF state, but production admission "
        "still refuses and admitted live profiles retain zero native-subagent limits; "
        "Worker child-run cards therefore do not claim a Codex-native agent tree.",
    ),
    "canonical-execution-inspector": _coverage(
        "boltrig/models/execution_results.py",
        ("missing", "missing", "missing", "missing", "missing"),
        "The canonical phase, assignment, result and verification records have no "
        "public projection or Worker inspector for attempts, pins, evidence, findings, "
        "blockers, handoffs, native-agent topology or verifier outcomes.",
    ),
}


# Product contracts whose absence cuts across several otherwise-covered routes.
# These are explicit rows because a route/manifest/source census cannot discover
# a capability which Boltrig has not modelled yet.  Keeping them in the
# executable ledger prevents a green surface count from being reported as
# whole-product completeness.
STRATEGIC_PRODUCT_FEATURES: dict[str, FeatureCoverage] = {
    "compliance-archive-and-complete-erasure": _coverage(
        "boltrig/kernel/account_profile_routes.py:account summary export",
        ("worker", "operator", "missing", "worker", "missing"),
        "Worker labels the synchronous account download as a bounded summary. "
        "Boltrig still lacks one asynchronous, scoped archive/erasure job spanning "
        "conversation bodies, Knowledge originals, Memory, artifacts, voice and "
        "audit evidence with progress, failure and retry receipts.",
    ),
    "provider-oauth-exchange": _coverage(
        "boltrig/kernel/platform_routes/integration_setup.py",
        ("worker", "missing", "missing", "worker", "missing"),
        "Worker discovers certified integration metadata and the native shell "
        "reports its strict callback readiness, but no provider-specific kernel "
        "authorization, HTTPS callback, code exchange, account selection, token "
        "rotation or revocation-recovery contract exists.",
    ),
    "approval-policy-delegation-and-dry-run": _coverage(
        "docs/proposals/approval-policies-and-dry-run.md",
        ("missing", "missing", "missing", "missing", "missing"),
        "Exact per-action HITL works, but Boltrig has no first-class versioned "
        "approval/delegation policy, decision-basis projection or authoritative "
        "no-side-effect execution plan. Worker must not invent these from a "
        "blocking-verb list or a client-side preview.",
    ),
    "provider-reconciled-cost-history": _coverage(
        "boltrig/kernel/cost.py",
        ("worker", "worker", "worker", "missing", "missing"),
        "Worker exposes governed limits and current scoped estimates, but Boltrig "
        "does not yet retain time-bucketed provider-reconciled history or a "
        "dispute/reconciliation lifecycle; workflow, realtime voice and direct "
        "paid-adapter charging are also incomplete.",
    ),
    "gateway-workload-identity-and-shared-run-tokens": _coverage(
        "services/channel_gateway/app.py",
        ("worker", "worker", "missing", "worker", "missing"),
        "Desired/observed channel state, a show-once scoped token and durable "
        "single-owner channel leases exist. Autonomous workload-identity delivery "
        "and a reviewed cross-replica MCP run-token registry do not, so deployment "
        "still places the gateway token file and multi-API routing has an explicit "
        "sticky-routing boundary.",
    ),
    "shared-familiar-phenotype-and-emotion": _coverage(
        "boltrig/emotion/relay.py",
        ("worker", "missing", "missing", "worker", "missing"),
        "Worker renders the canonical identity genotype and bounded live activity, "
        "but richer phenotype, gesture, mood and voice-amplitude state has no "
        "tenant-scoped durable cross-replica contract shared by web, native and "
        "local Familiar consumers.",
    ),
    "memory-engine-and-provider-recovery": _coverage(
        "boltrig/memory/bootstrap.py",
        ("missing", "deployment", "worker", "missing", "missing"),
        "Worker owns the canonical fact, recall, feedback and ingestion paths, but "
        "Boltrig has no safe projection of the effective process-start memory engine "
        "and provider fan-out, credential/readiness boundary or governed provider "
        "repair lifecycle.",
    ),
    "builtin-adapter-schema-reconciliation": _coverage(
        "scripts/resync-builtin-verbs.py",
        ("missing", "deployment", "missing", "missing", "missing"),
        "A code upgrade can leave tenant-persisted verb definitions behind the "
        "installed built-in adapter implementation. The repair script is an "
        "operator action; no durable drift projection, exact-snapshot reconciliation "
        "or recovery receipt exists.",
    ),
    "credential-backed-external-knowledge-projections": _coverage(
        "boltrig/knowledge/projections.py",
        ("worker", "missing", "missing", "worker", "missing"),
        "Supermemory and Mem0 remain visible but explicitly unavailable, and older "
        "enabled rows are repaired to that honest state. Credential binding, provider "
        "health, compile/erase and recovery adapters do not exist, so Worker cannot "
        "enable them or claim an external projection lifecycle.",
    ),
}


# Ordinary controls that reach canonical backend contracts but still expose
# implementation-shaped structured data. These are explicit rows so backend
# parity cannot be reported as a polished primary-surface lifecycle.
PRIMARY_SURFACE_EXPERIENCE_FEATURES: dict[str, FeatureCoverage] = {
    "guided-structured-authoring": _coverage(
        "apps/worker/src/components/OrganisationWorkspaceSections.tsx",
        ("worker", "missing", "worker", "worker", "worker"),
        "Organisation scopes/settings/permissions, evaluation objects, workflow "
        "parameters and loop bindings, advanced channel policy and local command "
        "argv remain JSON-oriented. They are functional, but need schema-derived "
        "forms and scoped pickers that preserve the same exact governed route bodies.",
    ),
    "scoped-reference-pickers": _coverage(
        "apps/worker/src/components/ParityViews.tsx",
        ("worker", "missing", "worker", "worker", "worker"),
        "Several work ownership/parent and audit-run controls still ask ordinary "
        "users for opaque identifiers instead of caller-scoped searchable pickers; "
        "the backend contracts work but primary-surface discoverability is incomplete.",
    ),
}


INTERNAL_OR_LEGACY_FEATURES: dict[str, FeatureCoverage] = {
    "worker-live-event-vocabulary": _coverage(
        "boltrig/fleet/chat_event_projection.py",
        ("worker", "worker", "worker", "worker", "worker"),
        "The browser boundary is a closed reviewed projection; artifacts refresh through their governed API, rejected outputs and withheld internal frames remain explicit, and the shared SDK consumes every admitted kind.",
    ),
    "direct-mutation-approval-finalization": _coverage(
        "boltrig/kernel/held_call.py:name_redeemer caller lane",
        ("worker", "worker", "worker", "worker", "worker"),
        "Every fixed Worker direct control has an owning completion lane: non-secret typed inputs use exact requester-owned replay, while one-time secrets and snapshot-bound recoveries use purpose-specific contracts.",
    ),
    "workflow-synthesis-learning": _coverage(
        "boltrig/workflows/generator.py",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Typed and tested, but select/generate and outcome promotion have no production caller.",
    ),
    "ultracode-mastra": _coverage(
        "boltrig/fleet/ultracode.py",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Internal Hatchet task with no governed ordinary entry; scheduled cutover residue, not a Worker feature.",
    ),
    "legacy-agent-runtimes": _coverage(
        "boltrig/fleet/runtime.py",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Pi/Hermes/OpenCode/Rivet paths are disabled rollback residue; Codex is the target runtime.",
    ),
    "message-queue-and-ocr-seams": _coverage(
        "boltrig/adapters/builtin/mq_file.py",
        ("not_product", "not_product", "not_product", "not_product", "not_product"),
        "Kafka, RabbitMQ and OCR functions deliberately raise SeamUnavailable.",
    ),
    "external-audit-timestamp-kms": _coverage(
        "boltrig/kernel/security_events.py",
        ("worker", "deployment", "deployment", "worker", "deployment"),
        "Worker distinguishes local fallback; reviewed TSA/KMS composition is an external deployment requirement.",
    ),
}


ALL_NON_HTTP_FEATURES = {
    **{f"manifest:{key}": value for key, value in MANIFEST_FEATURES.items()},
    **{f"manifest-field:{key}": value for key, value in NESTED_MANIFEST_FIELDS.items()},
    **{f"manifest-extra:{key}": value for key, value in MANIFEST_EXTRA_FEATURES.items()},
    **{f"background:{key}": value for key, value in BACKGROUND_FEATURES.items()},
    **{f"native:{key}": value for key, value in NATIVE_COMMANDS.items()},
    **{f"native-plugin:{key}": value for key, value in NATIVE_PLUGIN_FEATURES.items()},
    **{f"cli:{key}": value for key, value in CLI_COMMAND_FEATURES.items()},
    **{f"governed-control:{key}": value for key, value in GOVERNED_WORKER_CONTROL_FEATURES.items()},
    **{f"strategic-runtime:{key}": value for key, value in STRATEGIC_RUNTIME_FEATURES.items()},
    **{f"strategic-product:{key}": value for key, value in STRATEGIC_PRODUCT_FEATURES.items()},
    **{f"surface-experience:{key}": value for key, value in PRIMARY_SURFACE_EXPERIENCE_FEATURES.items()},
    **{f"internal:{key}": value for key, value in INTERNAL_OR_LEGACY_FEATURES.items()},
}
