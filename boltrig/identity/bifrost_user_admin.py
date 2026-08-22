"""Bounded internal Bifrost administration for scoped BYO model bindings."""

from __future__ import annotations

from collections.abc import Mapping
import re

from typing import Any, Protocol
from urllib.parse import quote, urlsplit

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

#: models.dev's provider-id shape; the only names the custom path creates.
_CUSTOM_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def _custom_base_url(value: str | None) -> str:
    """A custom provider's endpoint: absolute http(s), no secrets in the URL.

    Deliberately looser than ``admin_base`` (which pins the INTERNAL gateway to
    a known host and an exact /v1 path): this is an EXTERNAL provider address
    the operator chose, the same trust the self-hosted Ollama path already
    extends. Userinfo, query and fragment are refused because a credential
    belongs in the sealed key, never in an address that gets logged.
    """
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > 200 or candidate != candidate.strip():
        raise BifrostUserBindingUnavailable(
            "the provider needs the URL of its OpenAI-compatible endpoint"
        )
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise BifrostUserBindingUnavailable("the provider base URL is invalid")
    return candidate.rstrip("/")


class _Binding(Protocol):
    provider: str
    model_id: str
    virtual_key: str


def _virtual_key_identity(
    row: dict[str, Any], provider: str, provider_key_id: str, raw_model: str
) -> tuple[str, str]:
    virtual_key_id = safe_identifier(row.get("id"), "virtual key id")
    virtual_key = ascii_secret(row.get("value"), "the saved access key")
    if row.get("is_active") is not True:
        raise BifrostUserBindingUnavailable("the saved connection is switched off")
    configs = row.get("provider_configs")
    if not isinstance(configs, list) or len(configs) != 1 or not isinstance(configs[0], dict):
        raise BifrostUserBindingUnavailable("the saved connection does not match this model")
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
        raise BifrostUserBindingUnavailable("the saved connection does not match this model")
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

    async def provider_key_status(self, provider: str, key_id: str) -> str | None:
        """The gateway's own health verdict for one provider key, or None.

        Distinguishes "the endpoint never answered" from "the endpoint answered
        without the model", which need opposite user fixes. Diagnostic only:
        callers must not gate on it, and any failure reads as unknown.
        """
        try:
            payload = await self._http.request_json(
                "GET",
                f"{self._http.base}api/providers/{quote(provider, safe='')}/keys",
            )
        except BifrostUserBindingUnavailable:
            return None
        rows = payload.get("keys")
        if not isinstance(rows, list):
            return None
        for row in rows:
            if isinstance(row, dict) and row.get("id") == key_id:
                status = row.get("status")
                return status if isinstance(status, str) else None
        return None

    async def revoke_metadata(self, sealed: dict[str, Any]) -> None:
        provider = str(sealed.get("provider") or "").lower()
        # Custom providers are legitimate stored rows now; the gate is the id
        # SHAPE, not membership of the native set, or revoking a custom
        # binding would strand its keys in Bifrost forever.
        if provider not in BIFROST_PROVIDERS and _CUSTOM_ID.fullmatch(provider) is None:
            raise BifrostUserBindingUnavailable(
                "the saved provider entry is invalid"
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
                "the saved connection could not be removed"
            )
        key_status, _payload = await self._http.request(
            "DELETE",
            f"{self._http.base}api/providers/{quote(provider, safe='')}/keys/"
            f"{quote(provider_key_id, safe='')}",
        )
        if key_status not in {200, 204, 404}:
            raise BifrostUserBindingUnavailable(
                "the saved key could not be removed"
            )

    async def ensure_provider(
        self, provider: str, *, base_url: str | None = None
    ) -> None:
        """Ensure the provider row exists - native, or custom with an address.

        A provider outside ``BIFROST_PROVIDERS`` has no native driver, so it is
        created with ``custom_provider_config``: Bifrost speaks the
        OpenAI-compatible dialect to the given base URL. An existing custom row
        whose stored address DIFFERS is refused rather than silently repointed:
        other scopes' keys may already ride it, and moving the address under
        them is the kind of quiet cross-tenant surprise this module refuses.
        """
        payload = await self._http.request_json(
            "GET", f"{self._http.base}api/providers"
        )
        rows = payload.get("providers")
        if not isinstance(rows, list):
            raise BifrostUserBindingUnavailable(
                "the provider list could not be read; try again shortly"
            )
        custom_url = _custom_base_url(base_url) if provider not in BIFROST_PROVIDERS else None
        for row in rows:
            if isinstance(row, dict) and row.get("name") == provider:
                if custom_url is None:
                    return
                config = row.get("custom_provider_config")
                stored = config.get("base_url") if isinstance(config, dict) else None
                if stored == custom_url:
                    return
                raise BifrostUserBindingUnavailable(
                    f"{provider} is already bound to a different endpoint; "
                    "remove that binding first or use its address"
                )
        body: dict[str, Any] = {"provider": provider}
        if custom_url is not None:
            body["custom_provider_config"] = {
                "base_provider_type": "openai",
                "base_url": custom_url,
            }
        status, _payload = await self._http.request(
            "POST", f"{self._http.base}api/providers", body
        )
        if status not in {200, 201, 409}:
            raise BifrostUserBindingUnavailable(
                "that provider could not be added; try again shortly"
            )

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
                "a conflicting key is already saved for this provider"
            )
        if status not in {200, 201}:
            raise BifrostUserBindingUnavailable(
                "the key could not be saved; check it and try again"
            )

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
                "saved connections could not be read; try again shortly"
            )
        matches = [
            row for row in rows if isinstance(row, dict) and row.get("name") == name
        ]
        if len(matches) > 1:
            raise BifrostUserBindingUnavailable(
                "duplicate saved connections were found for this model"
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
                        "the old connection could not be replaced"
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
                "the connection could not be created; try again shortly"
            )
        row = payload.get("virtual_key")
        if not isinstance(row, dict):
            raise BifrostUserBindingUnavailable(
                "the connection came back malformed; try again"
            )
        return _virtual_key_identity(row, provider, provider_key_id, raw_model)

__all__ = [
    "BIFROST_PROVIDERS",
    "BifrostUserAdmin",
    "BifrostUserBindingUnavailable",
]
