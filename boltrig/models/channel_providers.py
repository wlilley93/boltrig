"""Canonical channel-provider contracts.

This module is the single provider authority shared by governed lifecycle,
browser-safe projections and gateway reconciliation.  Provider credentials are
named references only; provider config is deliberately limited to non-secret,
tenant-authored settings.  Deployment topology (URLs, listeners and injected
test clients) belongs to the severed gateway deployment and is never accepted
from Worker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChannelProvider:
    id: str
    label: str
    transport: str
    credential_keys: tuple[str, ...]
    provider_config_keys: tuple[str, ...] = ()
    required_provider_config: tuple[str, ...] = ()
    activation: str = "automatic"
    shipped: bool = True


CHANNEL_PROVIDERS: dict[str, ChannelProvider] = {
    "webhook": ChannelProvider(
        "webhook", "Signed webhook", "webhook", ("signing",)
    ),
    "msteams": ChannelProvider(
        "msteams", "Teams-labelled signed webhook", "webhook", ("signing",)
    ),
    "slack": ChannelProvider(
        "slack", "Slack Socket Mode", "socket",
        ("signing", "app_token", "bot_token"),
    ),
    "telegram": ChannelProvider(
        "telegram", "Telegram bot", "socket", ("signing", "bot_token")
    ),
    "discord": ChannelProvider(
        "discord", "Discord bot", "socket", ("signing", "bot_token")
    ),
    "signal": ChannelProvider(
        "signal", "Signal", "socket", ("signing",),
        provider_config_keys=("account",),
        required_provider_config=("account",),
        activation="external_pairing",
    ),
    "whatsapp": ChannelProvider(
        "whatsapp", "WhatsApp", "socket", ("signing",),
        activation="external_pairing",
    ),
    "generic": ChannelProvider(
        "generic", "Generic socket surface", "socket", ("signing",),
        activation="deployment_managed",
    ),
    "voice": ChannelProvider(
        "voice", "Realtime voice", "socket", ("signing", "api_key"),
        provider_config_keys=(
            "model", "voice", "instructions", "speaker", "thread",
            "input_audio_price_per_million", "output_audio_price_per_million",
            "pricing_revision",
        ),
    ),
}

WEBHOOK_PLATFORMS: tuple[str, ...] = tuple(
    provider.id for provider in CHANNEL_PROVIDERS.values()
    if provider.transport == "webhook"
)
SOCKET_PLATFORMS: tuple[str, ...] = tuple(
    provider.id for provider in CHANNEL_PROVIDERS.values()
    if provider.transport == "socket"
)
CHANNEL_PLATFORMS: tuple[str, ...] = tuple(CHANNEL_PROVIDERS)

_FORBIDDEN_CONFIG_FRAGMENTS = (
    "secret", "token", "password", "api_key", "apikey", "credential",
    "http_url", "api_base", "bridge_base", "gateway_url", "kernel_url",
    "listen_host", "listen_port", "egress_allow", "http_client",
)


def provider_for(platform: str) -> ChannelProvider:
    """Return a supported provider, failing closed for unknown platform ids."""
    try:
        return CHANNEL_PROVIDERS[platform]
    except KeyError as exc:
        raise ValueError(f"unsupported channel platform: {platform}") from exc


def transport_for(platform: str) -> str:
    return provider_for(platform).transport


def _contains_forbidden_config_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            folded = str(key).strip().lower()
            if any(fragment in folded for fragment in _FORBIDDEN_CONFIG_FRAGMENTS):
                return True
            if _contains_forbidden_config_key(nested):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_config_key(item) for item in value)
    return False


def normalise_channel_config(
    platform: str,
    policy_config: dict[str, Any] | None,
    provider_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate and combine browser-visible, non-secret channel config.

    Existing policy fields such as ``addressing`` and ``self_onboard`` remain
    extensible data.  Secret-like or deployment-topology keys are rejected at
    any depth, preventing an opaque JSON textarea/client from smuggling provider
    material into the browser-visible ``channels.config`` row.
    """
    provider = provider_for(platform)
    policy = dict(policy_config or {})
    supplied_provider = dict(provider_config or {})
    if _contains_forbidden_config_key(policy) or _contains_forbidden_config_key(
        supplied_provider
    ):
        raise ValueError(
            "channel config may not contain secrets, credential names, or gateway topology"
        )
    unknown = sorted(set(supplied_provider) - set(provider.provider_config_keys))
    if unknown:
        raise ValueError(
            f"{platform} provider_config does not support: {', '.join(unknown)}"
        )
    missing = [
        key for key in provider.required_provider_config
        if not str(supplied_provider.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(
            f"{platform} provider_config requires: {', '.join(missing)}"
        )
    if supplied_provider:
        policy["provider"] = supplied_provider
    else:
        policy.pop("provider", None)
    return policy


def credential_reference_bundle(
    platform: str,
    supplied: dict[str, Any] | None,
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a sealed-store row containing reference metadata only.

    Values are external secret-store names, never secret material.  Configure
    merges supplied keys with the existing bundle so one credential can rotate
    without Worker learning or resending the others.
    """
    provider = provider_for(platform)
    refs: dict[str, dict[str, str]] = {}
    if isinstance(existing, dict) and existing.get("kind") == "channel_credentials_v1":
        for key, value in dict(existing.get("refs") or {}).items():
            if (
                key in provider.credential_keys
                and isinstance(value, dict)
                and str(value.get("ref") or "").strip()
            ):
                refs[key] = {
                    "store": str(value.get("store") or "env"),
                    "ref": str(value["ref"]).strip(),
                }
    for key, value in dict(supplied or {}).items():
        if key not in provider.credential_keys:
            raise ValueError(f"{platform} does not accept credential reference: {key}")
        ref = str(value or "").strip()
        if not ref:
            raise ValueError(f"credential reference {key} must be a non-empty name")
        refs[key] = {"store": "env", "ref": ref}
    return {
        "kind": "channel_credentials_v1",
        "platform": platform,
        "refs": refs,
    }


def credential_presence(
    platform: str, row: dict[str, Any] | None
) -> dict[str, bool]:
    provider = CHANNEL_PROVIDERS.get(platform)
    if provider is None:
        return {}
    if isinstance(row, dict) and row.get("kind") == "channel_credentials_v1":
        refs = dict(row.get("refs") or {})
        return {
            key: bool(isinstance(refs.get(key), dict) and refs[key].get("ref"))
            for key in provider.credential_keys
        }
    # Legacy rows contain the intake signing material/reference only.
    legacy_signing = bool(row and (row.get("ref") or row.get("secret")))
    return {
        key: legacy_signing if key == "signing" else False
        for key in provider.credential_keys
    }


def provider_public_descriptor(platform: str) -> dict[str, Any]:
    provider = CHANNEL_PROVIDERS.get(platform)
    if provider is None:
        return {
            "id": platform,
            "label": f"Unsupported provider ({platform})",
            "transport": "unsupported",
            "credential_keys": [],
            "provider_config_keys": [],
            "required_provider_config": [],
            "activation": "unsupported",
            "shipped": False,
            "capability": "unsupported",
        }
    return {
        "id": provider.id,
        "label": provider.label,
        "transport": provider.transport,
        "credential_keys": list(provider.credential_keys),
        "provider_config_keys": list(provider.provider_config_keys),
        "required_provider_config": list(provider.required_provider_config),
        "activation": provider.activation,
        "shipped": provider.shipped,
        # Deliberately not "certified" or "connected": those need observed proof.
        "capability": "shipped_adapter" if provider.shipped else "unsupported",
    }
