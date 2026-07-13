"""Config-only model profiles for Bifrost/gateway routing."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from boltrig.models import ModelEndpoint

from .runtime import runtime_for_provider


@dataclass(frozen=True)
class ModelProfile:
    """A named provider/model/base-url selection, never credential material."""

    name: str
    provider: str
    model: str
    base_url: str | None = None


@dataclass(frozen=True)
class ProfileRoute:
    """The resolved profile route and metadata safe for audit/telemetry."""

    profile: str
    provider: str
    model: str
    base_url: str | None
    runtime: str

    def audit_detail(self) -> dict[str, str]:
        detail = {
            "profile": self.profile,
            "provider": self.provider,
            "model": self.model,
            "runtime": self.runtime,
        }
        if self.base_url:
            detail["base_url"] = self.base_url
        return detail


def _profiles_from_env() -> dict[str, ModelProfile]:
    raw = os.environ.get("BOLTRIG_MODEL_PROFILES")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    profiles: dict[str, ModelProfile] = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        provider = cfg.get("provider")
        model = cfg.get("model")
        if not provider or not model:
            continue
        profiles[str(name)] = ModelProfile(
            name=str(name),
            provider=str(provider),
            model=str(model),
            base_url=str(cfg["base_url"]) if cfg.get("base_url") else None,
        )
    return profiles


def _profiles_from_context(extra: dict[str, Any]) -> dict[str, ModelProfile]:
    data = extra.get("model_profiles") or {}
    if not isinstance(data, dict):
        return {}
    profiles: dict[str, ModelProfile] = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict):
            continue
        provider = cfg.get("provider")
        model = cfg.get("model")
        if not provider or not model:
            continue
        profiles[str(name)] = ModelProfile(
            name=str(name),
            provider=str(provider),
            model=str(model),
            base_url=str(cfg["base_url"]) if cfg.get("base_url") else None,
        )
    return profiles


def select_model_profile(extra: dict[str, Any]) -> ModelProfile | None:
    """Resolve the requested profile from context first, then env config."""
    name = extra.get("model_profile") or extra.get("ai_profile")
    if not name:
        return None
    profiles = {**_profiles_from_env(), **_profiles_from_context(extra)}
    return profiles.get(str(name))


def apply_model_profile(
    endpoint: ModelEndpoint | None,
    profile: ModelProfile | None,
    *,
    tenant_id: str = "",
) -> tuple[ModelEndpoint | None, str | None, ProfileRoute | None]:
    """Apply a profile to an endpoint, returning endpoint/runtime/metadata."""
    if profile is None:
        return endpoint, None, None
    runtime = runtime_for_provider(profile.provider)
    if runtime is None:
        return endpoint, None, None
    if endpoint is None:
        endpoint = ModelEndpoint(
            id=f"profile:{profile.name}",
            tenant_id=tenant_id,
            kind=profile.provider,
            model=profile.model,
            base_url=profile.base_url,
            data_class="standard",
        )
    routed = replace(
        endpoint,
        kind=profile.provider,
        model=profile.model,
        base_url=profile.base_url or endpoint.base_url,
    )
    return routed, runtime, ProfileRoute(
        profile=profile.name,
        provider=profile.provider,
        model=routed.model,
        base_url=routed.base_url,
        runtime=runtime,
    )
