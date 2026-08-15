"""Per-org / workspace / user AI-key resolution ([2026] VJS-COUNTY 8, D5).

The kernel resolves WHICH AI key a run uses through one helper, ``resolve_ai_key``,
with a fixed precedence:

    user  ->  workspace  ->  org  ->  manifest/env default

honouring the org-wide ``allow_own_ai_keys`` gate. When an org does NOT allow its
members to bring their own keys, a workspace/user AI-config row is IGNORED and only
the org row (or, absent that, the manifest/env-configured provider key) is used -
so a workspace or a user cannot bring their own key unless the org opts in.

Resolution returns an ``AiKeyResolution`` describing the chosen level plus the
SEALED ``credential_ref`` (the id of a row in ``credential_refs``) - NEVER the raw
key. The material is loaded, kernel-side and at call time, by
``load_ai_key_material`` and handed straight to one runtime call; it is never
returned to an agent, embedded in a result, or written to audit (SEC-05, K-20).

ADDITIVE + backward-compatible: a tenant with no AI-config rows (every existing
single-tenant deploy, and the backfilled default org with no keys) resolves to the
``default`` level with no credential_ref, and the runtime falls back to the
env-configured provider key exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AiKeyResolution:
    """The outcome of AI-key resolution - metadata only, never secret material.

    ``level`` is the level the key was resolved AT: ``user`` / ``workspace`` /
    ``org`` for a configured key, or ``default`` when no config applies and the
    caller should fall back to the manifest/env-configured provider key.
    ``credential_ref`` is the id of the SEALED credential to load (None for the
    default level). ``provider`` / ``model`` are the configured selection, and
    ``base_url`` is the optional endpoint URL the config names (None at the default
    level, and None when the config leaves it unset). These three drive model/provider
    ROUTING (D5): with a non-default resolution the spawner selects the runtime by
    ``provider`` and pins the endpoint's ``model`` / ``base_url`` - EXCEPT for
    sensitive-classified data, where the local endpoint wins regardless (SEC-12).
    """

    level: str
    scope_id: str | None = None
    modality: str = "text"
    credential_ref: str | None = None
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None

    @property
    def is_default(self) -> bool:
        """True when no org/workspace/user key applies (fall back to env/manifest)."""
        return self.credential_ref is None


def _from_config(level: str, config) -> AiKeyResolution:
    return AiKeyResolution(
        level=level,
        scope_id=config.scope_id,
        modality=getattr(config, "modality", "text"),
        credential_ref=config.credential_ref,
        provider=config.provider,
        model=config.model,
        base_url=getattr(config, "base_url", None),
    )


async def resolve_ai_key(
    store,
    tenant_id: str,
    *,
    workspace_id: str | None = None,
    user_id: str | None = None,
    modality: str = "text",
) -> AiKeyResolution:
    """Resolve a text or vision AI key, precedence user -> workspace -> org -> default.

    ``allow_own_ai_keys`` gate (read off the org): when it is False, a workspace or
    user row is skipped entirely (a member cannot bring their own key), so only the
    ORG row is considered before falling back to the manifest/env default. The org
    key always applies (an org may always set its own key). When the flag is True the
    full precedence holds: the caller's own key wins, then their active workspace's
    key, then the org key, then the env/manifest default. Vision first looks for a
    same-purpose key at each scope and falls back to that scope's text key.

    Every read is tenant-scoped (SEC-08): only rows inside ``tenant_id`` are ever
    consulted, and ``workspace_id`` is the caller's ALREADY-authorized active
    workspace (the session resolver re-checks membership every request), so this can
    never surface another org's or another workspace's key.
    """
    requested_modality = str(modality or "text").strip().lower()
    if requested_modality not in {"text", "vision"}:
        requested_modality = "text"
    org = await store.get_org(tenant_id)
    allow_own = bool(org.allow_own_ai_keys) if org is not None else False

    async def configured(level: str, scope_id: str) -> AiKeyResolution | None:
        cfg = await store.get_ai_config(
            tenant_id, level, scope_id, requested_modality
        )
        if cfg is not None:
            return _from_config(level, cfg)
        # A vision route is optional. When it is absent, the main text/API key
        # remains the fallback, allowing a multimodal primary endpoint to serve
        # vision without requiring a second credential.
        if requested_modality == "vision":
            cfg = await store.get_ai_config(tenant_id, level, scope_id, "text")
            if cfg is not None:
                return _from_config(level, cfg)
        return None

    if allow_own:
        if user_id:
            resolution = await configured("user", user_id)
            if resolution is not None:
                return resolution
        if workspace_id:
            resolution = await configured("workspace", workspace_id)
            if resolution is not None:
                return resolution

    # The org key always applies (independent of allow_own_ai_keys). The org row's
    # scope_id IS the tenant_id (the org id == tenant boundary).
    resolution = await configured("org", tenant_id)
    if resolution is not None:
        return resolution

    # No config at any applicable level: fall back to the manifest/env key.
    return AiKeyResolution(level="default")


async def load_ai_key_material(
    store, tenant_id: str, resolution: AiKeyResolution
) -> str | None:
    """Load the SEALED key material for a resolution, kernel-side, at call time.

    Returns the raw key string for a configured level, or ``None`` for the default
    level (the caller then uses the env/manifest key). The key is read from the
    RLS-fenced ``credential_refs`` table via ``get_credential_ref`` (the same sealed
    seam the channel signing secret uses) and is NEVER logged, returned to an agent,
    or written to audit - the caller hands it straight to one runtime call.
    """
    if resolution.credential_ref is None:
        return None
    ref = await store.get_credential_ref(tenant_id, resolution.credential_ref)
    if not ref:
        return None
    # Self-service sealed secret shape (mirrors channel signing secrets): the key
    # lives under "secret". Tolerate the external-store shape ("value") too.
    material = ref.get("secret")
    if material is None:
        material = ref.get("value")
    return material
