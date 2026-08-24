"""Fleet-manifest parse helpers (moved from config/manifest.py): ``${ENV}``
interpolation + the ``_parse_*`` family, composed by ``load_manifest``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from boltrig.config.dev_posture import DevelopmentPosture
from boltrig.config.environment import is_truthy
from boltrig.models import ModelEndpoint, RoleMapping, validate_cost_tier

from .manifest_types import (
    APPROVAL_TIMEOUT_SECONDS_FLOOR, _BUILTIN_MODULES,
    AdapterConfig, BudgetConfig, CredentialRef, EphemeralRuntime,
    FleetManifest, HierarchyConfig, HierarchyTier, HitlConfig, IdentityConfig,
    ModelsConfig, NamedAgentsConfig, NetworkConfig,
    PrivacyConfig,
)


# --- ${ENV} interpolation ---------------------------------------------------
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
_FALSE_VALUES = {"0", "false", "no", "off", "n", "f"}


def _interpolate(obj: Any, env: Mapping[str, str]) -> Any:
    """Recursively replace ``${VAR}`` / ``${VAR:-default}`` from ``env``."""
    if isinstance(obj, dict):
        return {k: _interpolate(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(v, env) for v in obj]
    if isinstance(obj, str):

        def repl(m: re.Match[str]) -> str:
            name, default = m.group(1), m.group(2)
            return env.get(name, default if default is not None else "")

        return _VAR.sub(repl, obj)
    return obj


# --- parse helpers ----------------------------------------------------------
def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if is_truthy(str(value)):
        return True
    if str(value).strip().lower() in _FALSE_VALUES:
        return False
    return default


def _parse_credential(raw: Any) -> CredentialRef | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        return CredentialRef(id=raw, ref=raw)
    cred_id = str(raw["id"])
    return CredentialRef(
        id=cred_id,
        store=str(raw.get("store", "env")),
        ref=str(raw.get("ref") or cred_id),
        kind=str(raw.get("kind", "api_key")),
    )


def _parse_identity(raw: Mapping[str, Any], tenant_id: str) -> IdentityConfig:
    provider = str(raw.get("provider", "oidc"))
    # M13: the manifest can advertise ``provider: saml`` but no SAML assertion
    # validator is wired anywhere (``SamlVerifier.verify`` raises), and resolver
    # selection never reads this field - so a deployment that sets it would
    # silently run env-selected auth while the operator believes SAML is
    # enforced. Fail loudly at load rather than boot a false belief. (SAML stays
    # a seam: supply a concrete assertion validator and select it explicitly.)
    if provider == "saml":
        raise ValueError(
            "identity.provider 'saml' is not implemented; set provider to "
            "'oidc' or 'cf-access' (or supply a SAML assertion validator and "
            "wire it explicitly). See audit finding M13."
        )
    mappings = tuple(
        RoleMapping(
            tenant_id=tenant_id,
            idp_group=str(m["idp_group"]),
            role=str(m["role"]),
            scope=dict(m.get("scope") or {}),
        )
        for m in (raw.get("role_mappings") or [])
    )
    return IdentityConfig(
        provider=provider,
        issuer=raw.get("issuer"),
        audience=raw.get("audience"),
        jwks_uri=raw.get("jwks_uri"),
        metadata_url=raw.get("metadata_url"),
        role_mappings=mappings,
    )


def _parse_rate(value: Any) -> float | None:
    """One non-negative rate as a float, or None when absent/malformed/negative.

    FLOAT, never int. Coercing with int() here was half of a two-part bug (
    price_micros int()-ed it again): every model we route to costs LESS than 1
    micro/token, so an honest rate like 0.35 truncated to 0 and priced the model
    FREE. A NEGATIVE rate is dropped - a price must never become a credit.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_price(rate: Any) -> float | dict[str, float] | None:
    """One entry of the per-model price table, or None to drop it (FR-COST-04).

    Two shapes, both policy-as-data:
      * a SCALAR - one rate for every token (the historical shape), and
      * a MAPPING - the published rate card's ``{input, output}`` pair, because
        those are not the same price (they commonly differ by more than 2x) and
        an agent turn is heavily input-weighted, so billing the whole turn at the
        output rate over-bills it substantially.

    THE UNIT is micros per token, which IS the published USD-per-1M-tokens figure:
    a micro is $0.000001, so $0.35 per 1,000,000 tokens = 0.35 micros/token. Copy
    the rate card number in unchanged; there is no conversion to get wrong.

    A mapping keeps whichever legs parse; ``cost.py`` fills a missing leg from the
    other one rather than from zero. An entry with NO usable leg is dropped whole,
    so the model falls back to its cost tier instead of billing nothing at all -
    a silent zero also bypasses the budget gate, since a cost of zero always
    passes a ceiling check.
    """
    if isinstance(rate, Mapping):
        legs = {
            leg: parsed
            for leg in ("input", "output")
            if (parsed := _parse_rate(rate.get(leg))) is not None
        }
        return legs or None
    return _parse_rate(rate)


def _parse_models(raw: Mapping[str, Any], tenant_id: str) -> ModelsConfig:
    endpoints = tuple(
        ModelEndpoint(
            id=str(e["id"]),
            tenant_id=tenant_id,
            kind=str(e.get("kind", "anthropic")),
            model=str(e["model"]),
            base_url=e.get("base_url"),
            fallback=e.get("fallback"),
            data_class=str(e.get("data_class", "standard")),
            modalities=tuple(e.get("modalities") or ("text",)),
        )
        for e in (raw.get("endpoints") or [])
    )
    # Per-model price table (FR-COST-04): {model_name: micros_per_token, or the
    # rate card's {input, output} pair of them}. A malformed entry is dropped
    # rather than failing load, so a bad price never blocks boot (the model just
    # falls back to its cost-tier default). See _parse_price for both shapes.
    prices: dict[str, float | dict[str, float]] = {}
    for name, rate in (raw.get("prices") or {}).items():
        parsed_price = _parse_price(rate)
        if parsed_price is not None:
            prices[str(name)] = parsed_price
    return ModelsConfig(
        endpoints=endpoints,
        default=raw.get("default"),
        sensitive_endpoint=raw.get("sensitive_endpoint"),
        prices=prices,
    )


def _parse_budget(raw: Any) -> BudgetConfig | None:
    if not raw:
        return None
    return BudgetConfig(
        token_limit=raw.get("token_limit"),
        cost_limit_micros=raw.get("cost_limit_micros"),
        hard_stop=bool(raw.get("hard_stop", True)),
        window=str(raw.get("window", "run")),
    )


def _parse_tier(raw: Mapping[str, Any]) -> HierarchyTier:
    skills = raw.get("skills", raw.get("supported_skills", ["*"]))
    return HierarchyTier(
        name=str(raw["name"]),
        runtime=str(raw.get("runtime", "codex")),
        model_endpoint=raw.get("model_endpoint"),
        max_depth=int(raw.get("max_depth", 3)),
        supported_skills=_as_tuple(skills),
        cost_tier=validate_cost_tier(str(raw.get("cost_tier", "standard"))),
        department=raw.get("department"),
        budget=_parse_budget(raw.get("budget")),
        purpose=str(raw.get("purpose") or ""),
        brief=str(raw.get("brief") or ""),
    )


def _parse_hierarchy(raw: Mapping[str, Any]) -> HierarchyConfig:
    tier1 = _parse_tier(raw["tier1"]) if raw.get("tier1") else None
    tier2 = tuple(_parse_tier(t) for t in (raw.get("tier2") or []))
    return HierarchyConfig(tier1=tier1, tier2=tier2)


def _parse_named_agents(raw: Mapping[str, Any]) -> NamedAgentsConfig:
    from .manifest_agents import parse_named_agents

    return parse_named_agents(
        raw, as_tuple=_as_tuple, parse_budget=_parse_budget
    )


def resolved_named_agents(manifest: FleetManifest) -> NamedAgentsConfig:
    from .manifest_agents import resolve_named_agents
    return resolve_named_agents(manifest)


def _parse_ephemeral(raw: Mapping[str, Any]) -> EphemeralRuntime:
    skills = raw.get("supported_skills", raw.get("skills", ["*"]))
    return EphemeralRuntime(
        name=str(raw["name"]),
        runtime=str(raw.get("runtime", "codex")),
        supported_skills=_as_tuple(skills),
        max_depth=int(raw.get("max_depth", 2)),
        cost_tier=validate_cost_tier(str(raw.get("cost_tier", "cheap"))),
        model_endpoint=raw.get("model_endpoint"),
    )


def _parse_adapter(raw: Mapping[str, Any]) -> AdapterConfig:
    adapter_id = str(raw["id"])
    return AdapterConfig(
        id=adapter_id,
        runtime=str(raw.get("runtime", "http")),
        credential=_parse_credential(raw.get("credential")),
        version=str(raw.get("version", "0.1.0")),
        source=str(raw.get("source", "builtin")),
        module_ref=str(raw.get("module_ref") or _BUILTIN_MODULES.get(adapter_id, "")),
    )


def _parse_development_posture(raw: Mapping[str, Any]) -> DevelopmentPosture:
    """Parse ``development_posture`` into a ``dev_posture.DevelopmentPosture``.

    An absent block yields ``DevelopmentPosture()`` (enabled False); a malformed
    or absent ``expires_at`` yields ``expires_at=None`` and a malformed ``covers``
    yields ``()``. ``dev_posture.posture_block`` refuses both: the failure mode of
    a bad date or a bad author list must be full four-eyes, never an unbounded or
    unbounded-in-scope suspension of it.
    """
    from datetime import datetime

    block = raw.get("development_posture")
    if not isinstance(block, Mapping):
        return DevelopmentPosture()
    expires: datetime | None = None
    stated = block.get("expires_at")
    if isinstance(stated, datetime):
        expires = stated
    elif isinstance(stated, str):
        try:
            expires = datetime.fromisoformat(stated)
        except ValueError:
            expires = None
    # `covers` names the authors the declaration was made in respect of (D3);
    # absent or malformed yields (), which covers nobody and refuses everything.
    stated = block.get("covers")
    covers = tuple(str(v).strip() for v in stated if str(v).strip()) if isinstance(stated, (list, tuple)) else ()
    return DevelopmentPosture(
        enabled=_as_bool(block.get("enabled", False)),
        expires_at=expires,
        declared_by=str(block.get("declared_by") or ""),
        reason=str(block.get("reason") or ""),
        covers=covers,
    )


def _parse_hitl(raw: Mapping[str, Any]) -> HitlConfig:
    return HitlConfig(
        primary_channel=str(raw.get("primary_channel", "slack")),
        notify_via=_as_tuple(raw.get("notify_via")),
        approval_timeout_seconds=int(
            raw.get("approval_timeout_seconds", APPROVAL_TIMEOUT_SECONDS_FLOOR)
        ),
        escalation_chain=_as_tuple(raw.get("escalation_chain")),
        blocking_verbs=_as_tuple(raw.get("blocking_verbs")),
    )


def _parse_network(raw: Mapping[str, Any]) -> NetworkConfig:
    return NetworkConfig(
        air_gapped=_as_bool(raw.get("air_gapped", False)),
        https_proxy=raw.get("https_proxy"),
        ca_bundle=raw.get("ca_bundle"),
        allowed_domains=_as_tuple(raw.get("allowed_domains")),
        blocked_domains=_as_tuple(raw.get("blocked_domains")),
    )


def _parse_privacy(raw: Mapping[str, Any]) -> PrivacyConfig:
    return PrivacyConfig(
        pii_redaction=_as_bool(raw.get("pii_redaction", False)),
        data_residency=raw.get("data_residency"),
        retention_days=raw.get("retention_days"),
        redact_fields=_as_tuple(raw.get("redact_fields")),
    )


def _tighten_cap(default: int, raw_value: Any) -> int:
    """Resolve an attachment cap: a manifest may only TIGHTEN it, never loosen it
    ([2026] VJS-COUNTY 3, D2). Absent/malformed manifest value keeps the code
    default; a supplied value is clamped into ``[0, default]`` so it can only ever
    reduce the ceiling (0 disables attachments entirely, a valid tightening)."""
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return min(default, max(0, value))
