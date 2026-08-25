"""``BifrostUserTransport`` is the fail-closed scoped administration transport."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

_INTERNAL_HOSTS = frozenset({"bifrost", "localhost", "127.0.0.1", "::1"})
_MAX_BODY = 512 * 1024
_MAX_SECRET = 8192
_TIMEOUT_SECONDS = 5.0
_SAFE_ID = re.compile(r"[A-Za-z0-9._~-]{1,160}\Z")


class BifrostUserBindingUnavailable(RuntimeError):
    """A scoped Bifrost binding could not be proven usable."""


def admin_base(value: str | None) -> str:
    if not value or value != value.strip():
        raise BifrostUserBindingUnavailable("the model gateway is not configured")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise BifrostUserBindingUnavailable("the model gateway configuration is invalid") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or (parsed.hostname or "").lower() not in _INTERNAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise BifrostUserBindingUnavailable("the model gateway configuration is invalid")
    return value.rstrip("/")[:-3]


def ascii_secret(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_SECRET
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise BifrostUserBindingUnavailable(f"{label} is unavailable")
    return value


def safe_identifier(value: object, label: str) -> str:
    if type(value) is not str or _SAFE_ID.fullmatch(value) is None:
        raise BifrostUserBindingUnavailable(f"{label} is invalid")
    return value


class BifrostUserTransport:
    """Identity-decoded, no-redirect, bounded internal Bifrost transport."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        source = os.environ if env is None else env
        self.base = f"{admin_base(source.get('BOLTRIG_MODEL_GATEWAY_URL'))}/"
        self._management_key = source.get("BOLTRIG_BIFROST_MANAGEMENT_KEY") or ""
        self._inference_key = source.get("BOLTRIG_MODEL_GATEWAY_KEY") or ""
        self._client = client

    def inference_headers(self, virtual_key: str) -> dict[str, str]:
        headers = {
            "accept": "application/json",
            "accept-encoding": "identity",
            "x-bf-vk": ascii_secret(virtual_key, "Bifrost virtual key"),
        }
        if self._inference_key:
            key = ascii_secret(self._inference_key, "gateway key")
            headers["authorization"] = f"Bearer {key}"
        return headers

    def openai_compatible_route(
        self, virtual_key: str
    ) -> tuple[str, str, tuple[tuple[str, str], ...]]:
        """Return an internal inference route for OpenAI-compatible clients.

        The client library owns ``Authorization`` through its ``api_key``
        parameter, while Bifrost's exact tenant/model ceiling remains the
        separate ``x-bf-vk`` header.  When inference authentication is disabled,
        the virtual key is also a valid OpenAI-style bearer and avoids inventing
        a second credential.
        """

        virtual = ascii_secret(virtual_key, "Bifrost virtual key")
        api_key = (
            ascii_secret(self._inference_key, "gateway key") if self._inference_key else virtual
        )
        return f"{self.base}v1", api_key, (("x-bf-vk", virtual),)

    async def request_json(
        self, method: str, url: str, *, headers: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        status, payload = await self.request(method, url, headers=headers)
        if not 200 <= status < 300:
            raise BifrostUserBindingUnavailable("Bifrost request was refused")
        return payload

    async def request(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        headers: Mapping[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        request_headers = dict(headers or self._admin_headers())
        if body is not None:
            request_headers["content-type"] = "application/json"
        client = self._client
        owned = client is None
        if client is None:
            client = httpx.AsyncClient(
                timeout=httpx.Timeout(_TIMEOUT_SECONDS, connect=1.0),
                follow_redirects=False,
                trust_env=False,
            )
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                async with client.stream(
                    method,
                    url,
                    headers=request_headers,
                    content=(
                        json.dumps(body, separators=(",", ":")).encode()
                        if body is not None
                        else None
                    ),
                ) as response:
                    response_body = await self._bounded_body(response)
                    status_code = response.status_code
            return status_code, self._json_object(response_body)
        except (httpx.HTTPError, TimeoutError) as error:
            raise BifrostUserBindingUnavailable("Bifrost is unavailable") from error
        finally:
            if owned:
                await client.aclose()

    def _admin_headers(self) -> dict[str, str]:
        headers = {"accept": "application/json", "accept-encoding": "identity"}
        if self._management_key:
            key = ascii_secret(self._management_key, "management key")
            headers["authorization"] = f"Bearer {key}"
        return headers

    async def _bounded_body(self, response: httpx.Response) -> bytes:
        if 300 <= response.status_code < 400:
            raise BifrostUserBindingUnavailable("Bifrost redirect was rejected")
        encoding = response.headers.get("content-encoding")
        if encoding is not None and encoding.strip().lower() != "identity":
            raise BifrostUserBindingUnavailable("Bifrost response encoding was rejected")
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                declared_size = int(declared)
            except ValueError as error:
                raise BifrostUserBindingUnavailable(
                    "Bifrost response length was invalid"
                ) from error
            if declared_size < 0 or declared_size > _MAX_BODY:
                raise BifrostUserBindingUnavailable("Bifrost response was too large")
        if response.is_stream_consumed:
            if len(response.content) > _MAX_BODY:
                raise BifrostUserBindingUnavailable("Bifrost response was too large")
            return response.content
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_raw():
            total += len(chunk)
            if total > _MAX_BODY:
                raise BifrostUserBindingUnavailable("Bifrost response was too large")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _json_object(response_body: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(response_body.decode("utf-8")) if response_body else {}
        except (UnicodeDecodeError, ValueError, RecursionError) as error:
            raise BifrostUserBindingUnavailable("Bifrost returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise BifrostUserBindingUnavailable("Bifrost returned an invalid response")
        return payload


__all__ = [
    "BifrostUserBindingUnavailable",
    "BifrostUserTransport",
    "ascii_secret",
    "safe_identifier",
]


def stored_base_url(row: dict[str, Any]) -> str | None:
    """The endpoint Bifrost actually recorded. BOTH spellings, network first.

    The gateway keeps a custom provider's address in ``network_config`` and
    drops it from ``custom_provider_config``, so reading only the latter saw
    ``None`` for every row and refused our own successful writes.
    """
    for key in ("network_config", "custom_provider_config"):
        section = row.get(key)
        if isinstance(section, dict):
            stored = section.get("base_url")
            if isinstance(stored, str) and stored:
                return stored
    return None
