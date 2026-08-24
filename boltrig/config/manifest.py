"""The fleet manifest: load it, type it, and seed the store from it (S11.2, P7).

Everything that varies between organisations is data, not code (P1/P7). The
fleet manifest is that data: who the org is, how it authenticates, which models
and adapters it uses, its flat named-agent roster, the ephemeral runtimes, the
HITL policy, and the network / privacy posture. ``load_manifest`` parses it into
frozen dataclasses (with ``${ENV}`` interpolation); ``apply_manifest`` seeds the
store so the kernel and fleet can run against it.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

import yaml

from boltrig.config.spawn_rules import parse_spawn_rules

# --- typed dataclasses + parse helpers (moved; re-exported) ----------------
# arc-1 structural move: the frozen dataclasses live in manifest_types.py and
# the parse family in manifest_parse.py; re-exported here because 40+ modules
# import them from boltrig.config.manifest.
from .manifest_types import (  # noqa: F401,E402
    APPROVAL_TIMEOUT_SECONDS_FLOOR as APPROVAL_TIMEOUT_SECONDS_FLOOR,
    _BUILTIN_MODULES as _BUILTIN_MODULES,
    AdapterConfig as AdapterConfig, BudgetConfig as BudgetConfig,
    ChatConfig as ChatConfig, CredentialRef as CredentialRef,
    EphemeralRuntime as EphemeralRuntime, FleetManifest as FleetManifest,
    HierarchyConfig as HierarchyConfig, HierarchyTier as HierarchyTier,
    HitlConfig as HitlConfig, IdentityConfig as IdentityConfig,
    ModelsConfig as ModelsConfig, NamedAgentConfig as NamedAgentConfig,
    NamedAgentsConfig as NamedAgentsConfig, NetworkConfig as NetworkConfig,
    PrivacyConfig as PrivacyConfig,
)
from .manifest_parse import (  # noqa: F401,E402
    _parse_development_posture as _parse_development_posture,
    _parse_models as _parse_models,
    resolved_named_agents as resolved_named_agents,
)
from .manifest_parse import (  # noqa: F401,E402  (private; load_manifest composes)
    _interpolate, _parse_adapter, _parse_ephemeral,
    _parse_hierarchy, _parse_hitl, _parse_identity, _parse_named_agents,
    _parse_network, _parse_privacy,
)
from .manifest_chat import (  # noqa: F401,E402  (moved with ChatConfig)
    DEFAULT_COMPACTION_KEEP_RECENT as DEFAULT_COMPACTION_KEEP_RECENT,
    DEFAULT_COMPACTION_THRESHOLD as DEFAULT_COMPACTION_THRESHOLD,
    DEFAULT_CONTINUITY_TOOL_NAME_CHARS as DEFAULT_CONTINUITY_TOOL_NAME_CHARS,
    DEFAULT_CONTINUITY_TOOL_PAIRS_PER_TURN as DEFAULT_CONTINUITY_TOOL_PAIRS_PER_TURN,
    DEFAULT_CONVERSATION_MAX_PAGE_SIZE as DEFAULT_CONVERSATION_MAX_PAGE_SIZE,
    DEFAULT_CONVERSATION_PAGE_SIZE as DEFAULT_CONVERSATION_PAGE_SIZE,
    DEFAULT_HEARTBEAT_SECONDS as DEFAULT_HEARTBEAT_SECONDS,
    DEFAULT_MAX_ATTACHMENTS as DEFAULT_MAX_ATTACHMENTS,
    DEFAULT_MAX_ATTACHMENT_BYTES as DEFAULT_MAX_ATTACHMENT_BYTES,
    DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES as DEFAULT_MAX_TOTAL_ATTACHMENT_BYTES,
    _parse_chat, _parse_heartbeat,
)


def load_manifest(path: str, *, env: Mapping[str, str] | None = None) -> FleetManifest:
    """Load + type the fleet manifest at ``path`` (S11.2).

    YAML is parsed, ``${ENV}`` references are interpolated from ``env`` (defaults
    to ``os.environ``), and the result is built into frozen dataclasses.
    """
    environ = env if env is not None else os.environ
    with open(path, "r", encoding="utf-8") as fh:
        raw_doc = yaml.safe_load(fh) or {}
    doc: dict[str, Any] = _interpolate(raw_doc, environ)

    tenant_id = str(doc["tenant_id"])
    if doc.get("agents") and doc.get("hierarchy"):
        raise ValueError("manifest must declare agents or legacy hierarchy, not both")
    return FleetManifest(
        organisation=str(doc.get("organisation", tenant_id)),
        tenant_id=tenant_id,
        locale_default=str(doc.get("locale_default", "en")),
        timezone_default=str(doc.get("timezone_default", "UTC")),
        identity=_parse_identity(doc.get("identity") or {}, tenant_id),
        models=_parse_models(doc.get("models") or {}, tenant_id),
        named_agents=(
            _parse_named_agents(doc.get("agents") or {})
            if doc.get("agents")
            else NamedAgentsConfig()
        ),
        hierarchy=_parse_hierarchy(doc.get("hierarchy") or {}),
        ephemeral_runtimes=tuple(
            _parse_ephemeral(r) for r in (doc.get("ephemeral_runtimes") or [])
        ),
        spawn_rules=parse_spawn_rules(doc.get("spawn_rules") or []),
        adapters=tuple(_parse_adapter(a) for a in (doc.get("adapters") or [])),
        hitl=_parse_hitl(doc.get("hitl") or {}),
        development_posture=_parse_development_posture(doc),
        network=_parse_network(doc.get("network") or {}),
        privacy=_parse_privacy(doc.get("privacy") or {}),
        chat=_parse_chat(doc.get("chat") or {}),
        extra={k: doc[k] for k in (
            "evaluation", "notifications", "personal_agents", "memory", "knowledge",
            "runtimes", "mcp", "chat", "stack", "mastra",
            "browser_cli", "langfuse", "reconcile", "distill",
        ) if k in doc},
    )


from .manifest_runtime import export_runtime_environment  # noqa: E402,F401


async def apply_manifest(
    kernel: Any,
    manifest: FleetManifest,
    *,
    load_builtin_adapters: bool = True,
    confirm_bulk_deactivate: bool = False,
) -> None:
    """Compatibility façade for the guarded store projection."""
    from .manifest_apply import apply_manifest as project_manifest

    await project_manifest(
        kernel,
        manifest,
        load_builtin_adapters=load_builtin_adapters,
        confirm_bulk_deactivate=confirm_bulk_deactivate,
    )
