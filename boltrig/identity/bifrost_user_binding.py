"""Kernel-only lifecycle for a scoped user/workspace/org Bifrost binding.

The browser's provider key is sealed by the existing ``ai_configs`` flow. This
facade turns it into one provider key and one exact-model virtual key, retaining
only sealed references. HTTP validation and Bifrost object administration live
in the adjacent transport/admin collaborators so this module owns only the
governed binding lifecycle.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from boltrig.models.model_id_policy import user_model_id

from .bifrost_user_admin import BIFROST_PROVIDERS, BifrostUserAdmin
from .bifrost_user_transport import (
    BifrostUserBindingUnavailable,
    ascii_secret,
    safe_identifier,
)

#: models.dev, which the onboarding picker is generated from, spells six
#: providers differently from Bifrost. The picker submits its own catalogue id
#: as the model prefix, so the kernel normalises here rather than asking the
#: browser to know Bifrost's naming.
_PROVIDER_ALIASES = {
    "google": "gemini",
    "google-generative-ai": "gemini",
    "x-ai": "xai",
    "amazon-bedrock": "bedrock",
    "fireworks-ai": "fireworks",
    "google-vertex": "vertex",
}

#: A catalogue provider id: lowercase, dot/dash/underscore, bounded. The same
#: shape models.dev uses, and the only names the custom path will create in
#: Bifrost - an id is an identifier, never an address or an instruction.
_CUSTOM_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


@dataclass(frozen=True, repr=False, slots=True)
class BifrostUserBinding:
    provider: str
    model_id: str
    provider_key_id: str
    virtual_key_id: str
    virtual_key: str
    credential_ref: str

    def __repr__(self) -> str:
        return "BifrostUserBinding(redacted=True)"


def binding_credential_ref(tenant_id: str, resolution: Any) -> str:
    level = str(getattr(resolution, "level", "") or "")
    scope_id = str(getattr(resolution, "scope_id", "") or "")
    modality = str(getattr(resolution, "modality", "text") or "text").lower()
    if not tenant_id or not level or not scope_id or modality not in {"text", "vision"}:
        raise BifrostUserBindingUnavailable(
            "scoped AI credential metadata is unavailable"
        )
    digest = hashlib.sha256(
        f"{tenant_id}\0{level}\0{scope_id}\0{modality}".encode()
    ).hexdigest()
    return f"bifrost_binding:{digest}"


def _binding_ids(
    tenant_id: str, resolution: Any, provider: str
) -> tuple[str, str, str]:
    """The credential ref, and the Bifrost ids to create under one provider.

    THE PROVIDER IS IN THE BIFROST IDS AND NOT IN THE REF, and the asymmetry is
    the whole point. The ref addresses OUR record for this scope and modality,
    which is one row per scope no matter who serves it; folding a provider into
    it would orphan every stored binding.

    Bifrost's key ids, though, are GLOBAL - not scoped per provider. Deriving
    them from scope alone meant every provider at one scope wanted the SAME id,
    so binding a second provider went: GET /providers/<new>/keys/<id> -> 404
    (that id is not under the new provider), therefore POST -> 409 Conflict
    (that id exists, under the OLD one). The 409 surfaced as "the key could not
    be saved; check it and try again", which blames the key for a collision it
    had no part in.

    Measured on dev 2026-08-24: a `zai-coding-plan` key held
    `bt-7dc143bd478d60d59b2dadd7bd80d874`; `cerebras` then asked for that exact
    id while `/api/providers/cerebras/keys` reported `total: 0`. So the first
    provider a tenant binds locks out every other one until someone deletes the
    row by hand - which is why this screen "never once worked" for anyone who
    tried a second provider.
    """
    ref = binding_credential_ref(tenant_id, resolution)
    digest = ref.rsplit(":", 1)[-1]
    scoped = hashlib.sha256(f"{digest}\0{provider}".encode()).hexdigest()
    return ref, f"bt-{scoped[:32]}", f"boltrig-{scoped[:24]}"


def _provider_and_model(resolution: Any) -> tuple[str, str, str]:
    """Resolve (provider, raw_model, model_id) - native or custom.

    A provider in ``BIFROST_PROVIDERS`` rides Bifrost's native driver. ANY
    other well-formed catalogue provider is bound as an OpenAI-compatible
    CUSTOM provider instead - Bifrost stores its ``base_url`` in
    ``custom_provider_config`` - so the full models.dev picker connects
    rather than 93% of it failing here at submit. A custom provider without
    a base URL is refused with the actionable half of the sentence, because
    an address is the one thing the custom path cannot invent.
    """
    try:
        # A user-connected model, not a kernel-pinned artifact: aliases like
        # ``:latest`` are the provider's own naming and are accepted (see
        # ``user_model_id``); shape and path rules still refuse the malformed.
        model_id = user_model_id(getattr(resolution, "model", None))
    except ValueError:
        raise BifrostUserBindingUnavailable(
            "that model name is not valid; use the exact name your provider "
            "lists, e.g. qwen3vl-abliterated:latest"
        ) from None
    configured = str(getattr(resolution, "provider", "") or "").strip().lower()
    configured = _PROVIDER_ALIASES.get(configured, configured)
    prefix, separator, provider_model = model_id.partition("/")
    provider = (
        _PROVIDER_ALIASES.get(prefix.lower(), prefix.lower())
        if separator
        else configured
    )
    if not provider or not _CUSTOM_PROVIDER_ID.fullmatch(provider):
        raise BifrostUserBindingUnavailable(
            "that provider is not recognised"
        )
    if provider not in BIFROST_PROVIDERS:
        base_url = str(getattr(resolution, "base_url", "") or "").strip()
        if not base_url:
            raise BifrostUserBindingUnavailable(
                f"{provider} needs the URL of its OpenAI-compatible endpoint; "
                "set the provider's base URL and try again"
            )
    if configured and configured not in {provider, "custom"}:
        raise BifrostUserBindingUnavailable(
            "the selected provider and model do not match"
        )
    raw_model = provider_model if separator else model_id
    if not raw_model or len(raw_model) > 160:
        raise BifrostUserBindingUnavailable("the selected model is invalid")
    return provider, raw_model, f"{provider}/{raw_model}"


class BifrostUserGateway:
    """Idempotent facade for a scope's exact Bifrost model credential."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._admin = BifrostUserAdmin(env=env, client=client)
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "BifrostUserGateway(redacted=True)"

    async def load(
        self, store: Any, tenant_id: str, resolution: Any
    ) -> BifrostUserBinding | None:
        ref = binding_credential_ref(tenant_id, resolution)
        sealed = await store.get_credential_ref(tenant_id, ref)
        if not isinstance(sealed, dict) or not sealed:
            return None
        provider, _raw_model, model_id = _provider_and_model(resolution)
        try:
            virtual_key = ascii_secret(sealed.get("secret"), "the saved access key")
            provider_key_id = safe_identifier(
                sealed.get("provider_key_id"), "provider key id"
            )
            virtual_key_id = safe_identifier(
                sealed.get("virtual_key_id"), "virtual key id"
            )
        except BifrostUserBindingUnavailable:
            return None
        expected_ref = getattr(resolution, "credential_ref", None)
        if (
            sealed.get("provider") != provider
            or sealed.get("model_id") != model_id
            or sealed.get("source_credential_ref") != expected_ref
        ):
            return None
        return BifrostUserBinding(
            provider=provider,
            model_id=model_id,
            provider_key_id=provider_key_id,
            virtual_key_id=virtual_key_id,
            virtual_key=virtual_key,
            credential_ref=ref,
        )

    async def ensure(
        self,
        store: Any,
        tenant_id: str,
        resolution: Any,
        provider_key: str,
    ) -> BifrostUserBinding:
        ascii_secret(provider_key, "provider key")
        existing = await self.load(store, tenant_id, resolution)
        if existing is not None and await self.is_usable(existing):
            return existing
        async with self._lock:
            existing = await self.load(store, tenant_id, resolution)
            if existing is not None and await self.is_usable(existing):
                return existing
            return await self._provision(
                store, tenant_id, resolution, provider_key
            )

    async def revoke(self, store: Any, tenant_id: str, resolution: Any) -> None:
        """Revoke the scope's virtual/provider keys before local deletion."""

        ref = binding_credential_ref(tenant_id, resolution)
        sealed = await store.get_credential_ref(tenant_id, ref)
        if not isinstance(sealed, dict) or not sealed:
            return
        await self._admin.revoke_metadata(sealed)
        await store.delete_credential_ref(tenant_id, ref)

    async def is_usable(self, binding: BifrostUserBinding) -> bool:
        return await self._admin.is_usable(binding)

    async def _provision(
        self,
        store: Any,
        tenant_id: str,
        resolution: Any,
        provider_key: str,
    ) -> BifrostUserBinding:
        provider, raw_model, model_id = _provider_and_model(resolution)
        ref, provider_key_id, virtual_key_name = _binding_ids(
            tenant_id, resolution, provider
        )
        previous = await store.get_credential_ref(tenant_id, ref)
        if (
            isinstance(previous, dict)
            and previous
            and previous.get("provider") != provider
        ):
            await self._admin.revoke_metadata(previous)
        await self._admin.ensure_provider(
            provider, base_url=getattr(resolution, "base_url", None)
        )
        await self._admin.ensure_provider_key(
            provider,
            provider_key_id,
            raw_model,
            provider_key,
            # Already on the resolution and already threaded to the spawner for
            # routing; the Bifrost admin was the one caller that never saw it.
            base_url=getattr(resolution, "base_url", None),
        )
        virtual_key_id, virtual_key = await self._admin.ensure_virtual_key(
            virtual_key_name, provider, provider_key_id, raw_model
        )
        binding = BifrostUserBinding(
            provider=provider,
            model_id=model_id,
            provider_key_id=provider_key_id,
            virtual_key_id=virtual_key_id,
            virtual_key=virtual_key,
            credential_ref=ref,
        )
        if not await self.is_usable(binding):
            # Two different user mistakes end here and need different fixes, so
            # ask the gateway which one happened rather than guessing: a key
            # whose provider fetch failed is a wrong ADDRESS; a healthy key
            # whose listing lacks the id is a wrong NAME.
            status = await self._admin.provider_key_status(provider, provider_key_id)
            if status == "list_models_failed":
                raise BifrostUserBindingUnavailable(
                    "your provider did not answer at that address; check the "
                    "URL (self-hosted servers are usually http://, not "
                    "https://), then enter the key and address again"
                )
            raise BifrostUserBindingUnavailable(
                f"your provider answered but does not list the model "
                f"'{raw_model}'; use the exact name it serves (self-hosted "
                "models usually include a tag, e.g. :latest)"
            )
        await store.set_credential_ref(
            tenant_id,
            ref,
            {
                "store": "bifrost",
                "ref": virtual_key_id,
                "secret": virtual_key,
                "provider": provider,
                "model_id": model_id,
                "source_credential_ref": getattr(
                    resolution, "credential_ref", None
                ),
                "provider_key_id": provider_key_id,
                "virtual_key_id": virtual_key_id,
            },
        )
        return binding


__all__ = [
    "BifrostUserBinding",
    "BifrostUserBindingUnavailable",
    "BifrostUserGateway",
    "binding_credential_ref",
]
