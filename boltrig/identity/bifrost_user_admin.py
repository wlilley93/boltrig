"""Bounded internal Bifrost administration for scoped BYO model bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .bifrost_user_transport import (
    BifrostUserBindingUnavailable,
    BifrostUserTransport,
    ascii_secret,
    safe_identifier,
)

BIFROST_PROVIDERS = frozenset(
    {
        "anthropic",
        "azure",
        "bedrock",
        "cerebras",
        "cohere",
        "elevenlabs",
        "fireworks",
        "gemini",
        "groq",
        "huggingface",
        "mistral",
        "nebius",
        "ollama",
        "openai",
        "openrouter",
        "parasail",
        "perplexity",
        "replicate",
        "runway",
        "sgl",
        "vertex",
        "vllm",
        "xai",
    }
)

#: Providers whose key payload carries a server URL in a provider-specific
#: block. Self-hosted providers only: the key is a placeholder and the address
#: is the real configuration. A table rather than an `if`, because Bifrost names
#: the block per provider and vllm will want its own when it is wired.
_PROVIDER_URL_CONFIG = {"ollama": "ollama_key_config"}

_MAX_MODEL_PAGES = 8


class _Binding(Protocol):
    provider: str
    model_id: str
    virtual_key: str


def _virtual_key_identity(
    row: dict[str, Any], provider: str, provider_key_id: str, raw_model: str
) -> tuple[str, str]:
    virtual_key_id = safe_identifier(row.get("id"), "virtual key id")
    virtual_key = ascii_secret(row.get("value"), "Bifrost virtual key")
    if row.get("is_active") is not True:
        raise BifrostUserBindingUnavailable("the Bifrost virtual key is inactive")
    configs = row.get("provider_configs")
    if not isinstance(configs, list) or len(configs) != 1 or not isinstance(configs[0], dict):
        raise BifrostUserBindingUnavailable("the Bifrost virtual-key scope differs")
    config = configs[0]
    keys = config.get("key_ids") if "key_ids" in config else config.get("keys")
    if isinstance(keys, list) and keys and isinstance(keys[0], dict):
        keys = [
            item.get("key_id") or item.get("id")
            for item in keys
            if isinstance(item, dict)
        ]
    if (
        config.get("provider") != provider
        or raw_model not in (config.get("allowed_models") or [])
        or (isinstance(keys, list) and provider_key_id not in keys)
    ):
        raise BifrostUserBindingUnavailable("the Bifrost virtual-key scope differs")
    return virtual_key_id, virtual_key


class BifrostUserAdmin:
    """Internal-only Bifrost HTTP client with bounded, identity-only responses."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._http = BifrostUserTransport(env=env, client=client)

    async def is_usable(self, binding: _Binding) -> bool:
        try:
            token = ""
            seen: set[str] = set()
            for _page in range(_MAX_MODEL_PAGES):
                suffix = f"&page_token={quote(token, safe='')}" if token else ""
                payload = await self._http.request_json(
                    "GET",
                    (
                        f"{self._http.base}v1/models?provider="
                        f"{quote(binding.provider, safe='')}&page_size=100{suffix}"
                    ),
                    headers=self._http.inference_headers(binding.virtual_key),
                )
                rows = payload.get("data")
                if not isinstance(rows, list):
                    return False
                if any(
                    isinstance(row, dict) and row.get("id") == binding.model_id
                    for row in rows
                ):
                    return True
                next_token = payload.get("next_page_token")
                if next_token in {None, ""}:
                    return False
                if type(next_token) is not str or len(next_token) > 1024 or next_token in seen:
                    return False
                seen.add(next_token)
                token = next_token
            return False
        except BifrostUserBindingUnavailable:
            return False

    async def revoke_metadata(self, sealed: dict[str, Any]) -> None:
        provider = str(sealed.get("provider") or "").lower()
        if provider not in BIFROST_PROVIDERS:
            raise BifrostUserBindingUnavailable(
                "the stored Bifrost provider binding is invalid"
            )
        provider_key_id = safe_identifier(
            sealed.get("provider_key_id"), "provider key id"
        )
        virtual_key_id = safe_identifier(
            sealed.get("virtual_key_id"), "virtual key id"
        )
        virtual_status, _payload = await self._http.request(
            "DELETE",
            f"{self._http.base}api/governance/virtual-keys/"
            f"{quote(virtual_key_id, safe='')}",
        )
        if virtual_status not in {200, 204, 404}:
            raise BifrostUserBindingUnavailable(
                "Bifrost refused the virtual-key revocation"
            )
        key_status, _payload = await self._http.request(
            "DELETE",
            f"{self._http.base}api/providers/{quote(provider, safe='')}/keys/"
            f"{quote(provider_key_id, safe='')}",
        )
        if key_status not in {200, 204, 404}:
            raise BifrostUserBindingUnavailable(
                "Bifrost refused the provider-key revocation"
            )

    async def ensure_provider(self, provider: str) -> None:
        payload = await self._http.request_json(
            "GET", f"{self._http.base}api/providers"
        )
        rows = payload.get("providers")
        if not isinstance(rows, list):
            raise BifrostUserBindingUnavailable(
                "Bifrost provider inventory is unavailable"
            )
        if any(isinstance(row, dict) and row.get("name") == provider for row in rows):
            return
        status, _payload = await self._http.request(
            "POST", f"{self._http.base}api/providers", {"provider": provider}
        )
        if status not in {200, 201, 409}:
            raise BifrostUserBindingUnavailable("Bifrost refused the selected provider")

    async def ensure_provider_key(
        self,
        provider: str,
        key_id: str,
        raw_model: str,
        provider_key: str,
        base_url: str | None = None,
    ) -> None:
        key_path = (
            f"{self._http.base}api/providers/{quote(provider, safe='')}/keys/"
            f"{quote(key_id, safe='')}"
        )
        check_status, check = await self._http.request("GET", key_path)
        payload = {
            "id": key_id,
            "name": key_id,
            "value": {"value": provider_key, "from_env": False},
            "models": [raw_model],
            "enabled": True,
        }
        # A KEYED provider's whole configuration is its key. A self-hosted one's
        # is its ADDRESS -- the key is a placeholder for a server that
        # authenticates nothing (see _KEYLESS_PROVIDERS in kernel/ai_key_routes)
        # and Bifrost asks for the URL in a provider-specific block instead.
        # Without it the POST is refused with "ollama_key_config.url is
        # required for Ollama keys", which is a 400 the operator sees as
        # "Bifrost refused the provider key" and cannot act on.
        config_field = _PROVIDER_URL_CONFIG.get(provider)
        if config_field:
            url = (base_url or "").strip()
            if not url:
                raise BifrostUserBindingUnavailable(
                    f"{provider} needs the URL of its server; set the endpoint's "
                    "base URL and try again"
                )
            payload[config_field] = {"url": url}
        if check_status == 404:
            status, _payload = await self._http.request(
                "POST",
                f"{self._http.base}api/providers/{quote(provider, safe='')}/keys",
                payload,
            )
        elif check_status == 200 and check.get("id") == key_id:
            status, _payload = await self._http.request("PUT", key_path, payload)
        else:
            raise BifrostUserBindingUnavailable(
                "the existing Bifrost key binding differs"
            )
        if status not in {200, 201}:
            raise BifrostUserBindingUnavailable("Bifrost refused the provider key")

    async def ensure_virtual_key(
        self, name: str, provider: str, provider_key_id: str, raw_model: str
    ) -> tuple[str, str]:
        listing = await self._http.request_json(
            "GET", f"{self._http.base}api/governance/virtual-keys"
        )
        rows = listing.get("virtual_keys")
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            raise BifrostUserBindingUnavailable(
                "Bifrost virtual-key inventory is unavailable"
            )
        matches = [
            row for row in rows if isinstance(row, dict) and row.get("name") == name
        ]
        if len(matches) > 1:
            raise BifrostUserBindingUnavailable(
                "the Bifrost virtual-key binding is ambiguous"
            )
        if matches:
            try:
                return _virtual_key_identity(
                    matches[0], provider, provider_key_id, raw_model
                )
            except BifrostUserBindingUnavailable:
                old_id = safe_identifier(matches[0].get("id"), "virtual key id")
                status, _payload = await self._http.request(
                    "DELETE",
                    f"{self._http.base}api/governance/virtual-keys/"
                    f"{quote(old_id, safe='')}",
                )
                if status not in {200, 204, 404}:
                    raise BifrostUserBindingUnavailable(
                        "Bifrost refused the virtual-key rotation"
                    )
        status, payload = await self._http.request(
            "POST",
            f"{self._http.base}api/governance/virtual-keys",
            {
                "name": name,
                "description": "Boltrig scoped model route",
                "provider_configs": [
                    {
                        "provider": provider,
                        "weight": 1,
                        "allowed_models": [raw_model],
                        "blacklisted_models": [],
                        "key_ids": [provider_key_id],
                    }
                ],
                "mcp_configs": [],
                "is_active": True,
            },
        )
        if status not in {200, 201}:
            raise BifrostUserBindingUnavailable(
                "Bifrost refused the scoped virtual key"
            )
        row = payload.get("virtual_key")
        if not isinstance(row, dict):
            raise BifrostUserBindingUnavailable(
                "Bifrost returned an invalid virtual key"
            )
        return _virtual_key_identity(row, provider, provider_key_id, raw_model)

__all__ = [
    "BIFROST_PROVIDERS",
    "BifrostUserAdmin",
    "BifrostUserBindingUnavailable",
]
