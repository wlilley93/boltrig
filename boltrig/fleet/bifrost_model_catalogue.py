"""Bounded, read-only discovery of the stack-owned Bifrost model catalogue.

This is deliberately an inventory seam, not a Bifrost administration client.
`BifrostModelCatalogue` performs one kind of request (``GET /v1/models``),
projects only model names and input modalities, and never returns gateway
topology, provider/key records, or the server-held bearer used for the request.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import unicodedata
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from typing import Literal, NotRequired, TypedDict
from urllib.parse import urlencode, urlsplit

import httpx

MAX_BIFROST_CATALOGUE_BODY_BYTES = 512 * 1024
MAX_BIFROST_CATALOGUE_MODELS = 500
MAX_BIFROST_CATALOGUE_PAGES = 8
BIFROST_CATALOGUE_PAGE_SIZE = 100
BIFROST_CATALOGUE_TIMEOUT_SECONDS = 1.5
BIFROST_CATALOGUE_CACHE_TTL_SECONDS = 5.0

_INTERNAL_GATEWAY_HOSTS = frozenset({"bifrost", "localhost", "127.0.0.1", "::1"})
_MAX_MODEL_TEXT_CHARS = 160
_MAX_MODALITIES = 8
_MAX_MODALITY_CHARS = 32
_MAX_PAGE_TOKEN_CHARS = 2048
_PAGE_TOKEN_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

CatalogueUnavailableReason = Literal[
    "not_configured",
    "invalid_gateway_configuration",
    "gateway_timeout",
    "gateway_unavailable",
    "gateway_redirect_rejected",
    "gateway_response_rejected",
    "response_too_large",
    "schema_invalid",
    "catalogue_too_large",
    "pagination_limit",
]


class BifrostModelView(TypedDict):
    id: str
    name: str
    input_modalities: NotRequired[list[str]]


class BifrostCatalogueResponse(TypedDict):
    status: Literal["ok", "unavailable"]
    models: list[BifrostModelView]
    reason: CatalogueUnavailableReason | None


PageFetcher = Callable[[str, Mapping[str, str], float, int], Awaitable[tuple[int, bytes]]]


class _ResponseTooLarge(RuntimeError):
    pass


class _ResponseEncodingRejected(RuntimeError):
    pass


class _SchemaInvalid(ValueError):
    pass


def unavailable(reason: CatalogueUnavailableReason) -> BifrostCatalogueResponse:
    """Return the one safe failure shape; partial catalogue data is never retained."""

    return {"status": "unavailable", "models": [], "reason": reason}


def _models_url(base_url: str | None) -> tuple[str | None, CatalogueUnavailableReason | None]:
    if base_url is None or not base_url:
        return None, "not_configured"
    if base_url != base_url.strip():
        return None, "invalid_gateway_configuration"
    try:
        split = urlsplit(base_url)
        port = split.port
    except ValueError:
        return None, "invalid_gateway_configuration"
    host = (split.hostname or "").lower()
    if (
        split.scheme not in {"http", "https"}
        or not split.netloc
        or host not in _INTERNAL_GATEWAY_HOSTS
        or split.username is not None
        or split.password is not None
        or split.query
        or split.fragment
        or split.path not in {"/v1", "/v1/"}
        or (port is not None and not 1 <= port <= 65535)
    ):
        return None, "invalid_gateway_configuration"
    return f"{base_url.rstrip('/')}/models", None


def _bearer_headers(key: str | None) -> Mapping[str, str] | None:
    headers: dict[str, str] = {"accept": "application/json"}
    if key is None or key == "":
        return headers
    if len(key) > 4096 or any(ord(character) < 0x21 or ord(character) > 0x7E for character in key):
        return None
    headers["authorization"] = f"Bearer {key}"
    return headers


async def _fetch_page(
    url: str,
    headers: Mapping[str, str],
    timeout_seconds: float,
    max_body_bytes: int,
) -> tuple[int, bytes]:
    """Fetch one identity-encoded page and cap raw bytes before parsing.

    ``httpx.Response.aiter_bytes()`` transparently decompresses content before
    yielding it, so an application length check around that iterator runs only
    after the decoder has allocated the expanded chunk.  The catalogue is a
    small JSON control-plane document; it has no reason to accept compression.
    Force identity encoding, reject an encoded response before reading it, and
    count the raw transport bytes instead.
    """

    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 0.75))
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        request_headers = dict(headers)
        request_headers["accept-encoding"] = "identity"
        async with client.stream("GET", url, headers=request_headers) as response:
            if not 200 <= response.status_code < 300:
                return response.status_code, b""
            content_encoding = response.headers.get("content-encoding")
            if content_encoding is not None and content_encoding.strip().lower() != "identity":
                raise _ResponseEncodingRejected
            declared = response.headers.get("content-length")
            if declared is not None:
                try:
                    declared_bytes = int(declared)
                except ValueError as error:
                    raise _ResponseTooLarge from error
                if declared_bytes < 0 or declared_bytes > max_body_bytes:
                    raise _ResponseTooLarge
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_raw():
                total += len(chunk)
                if total > max_body_bytes:
                    raise _ResponseTooLarge
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)


def _reject_json_constant(value: str) -> None:
    raise _SchemaInvalid(f"non-finite JSON constant: {value}")


def _bounded_text(label: str, value: object, maximum: int) -> str:
    if type(value) is not str:
        raise _SchemaInvalid(f"{label} must be an exact string")
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for character in value
        )
    ):
        raise _SchemaInvalid(f"{label} is outside the bounded public projection")
    return value


def _model(item: object) -> BifrostModelView:
    if not isinstance(item, Mapping):
        raise _SchemaInvalid("model entry must be an object")
    raw_id = item.get("id") if "id" in item else item.get("name")
    model_id = _bounded_text("model id", raw_id, _MAX_MODEL_TEXT_CHARS)
    raw_name = item.get("name") if "name" in item else model_id
    name = _bounded_text("model name", raw_name, _MAX_MODEL_TEXT_CHARS)
    projected: BifrostModelView = {"id": model_id, "name": name}
    architecture = item.get("architecture")
    if architecture is not None and not isinstance(architecture, Mapping):
        raise _SchemaInvalid("model architecture must be an object")
    if isinstance(architecture, Mapping) and "input_modalities" in architecture:
        raw_modalities = architecture.get("input_modalities")
        if type(raw_modalities) is not list or len(raw_modalities) > _MAX_MODALITIES:
            raise _SchemaInvalid("input modalities must be a bounded list")
        modalities = [
            _bounded_text("input modality", value, _MAX_MODALITY_CHARS) for value in raw_modalities
        ]
        if len(modalities) != len(set(modalities)):
            raise _SchemaInvalid("input modalities must be unique")
        projected["input_modalities"] = modalities
    return projected


def _page(body: bytes) -> tuple[list[BifrostModelView], str | None]:
    try:
        payload = json.loads(body.decode("utf-8"), parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise _SchemaInvalid("catalogue response is not strict JSON") from error
    if not isinstance(payload, Mapping):
        raise _SchemaInvalid("catalogue response must be an object")
    if type(payload.get("data")) is not list:
        raise _SchemaInvalid("catalogue response must carry a data list")
    models = [_model(item) for item in payload["data"]]
    ids = [item["id"] for item in models]
    if len(ids) != len(set(ids)):
        raise _SchemaInvalid("model ids must be unique within a page")
    raw_token = payload.get("next_page_token")
    if raw_token is None:
        next_page_token = None
    elif (
        type(raw_token) is not str
        or not raw_token
        or len(raw_token) > _MAX_PAGE_TOKEN_CHARS
        or any(character not in _PAGE_TOKEN_CHARS for character in raw_token)
    ):
        raise _SchemaInvalid("next page token is outside the bounded cursor format")
    else:
        next_page_token = raw_token
    return models, next_page_token


def _page_url(models_url: str, page_token: str | None) -> str:
    params = {"page_size": str(BIFROST_CATALOGUE_PAGE_SIZE)}
    if page_token is not None:
        params["page_token"] = page_token
    query = urlencode(params)
    return f"{models_url}?{query}"


class BifrostModelCatalogue:
    """Fetch a safe model-name projection from one boot-snapshotted gateway."""

    def __init__(
        self,
        *,
        env: Mapping[str, str] | None = None,
        page_fetcher: PageFetcher | None = None,
        cache_ttl_seconds: float = BIFROST_CATALOGUE_CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        source = os.environ if env is None else env
        self._base_url = source.get("BOLTRIG_MODEL_GATEWAY_URL") or None
        self._key = source.get("BOLTRIG_MODEL_GATEWAY_KEY") or None
        self._fetch_page = page_fetcher or _fetch_page
        self._cache_ttl_seconds = max(0.0, min(float(cache_ttl_seconds), 30.0))
        self._clock = clock
        self._cached: tuple[float, BifrostCatalogueResponse] | None = None
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return "BifrostModelCatalogue(redacted=True)"

    async def list_models(self) -> BifrostCatalogueResponse:
        cached = self._cached
        now = self._clock()
        if cached is not None and now < cached[0]:
            return deepcopy(cached[1])
        async with self._lock:
            cached = self._cached
            now = self._clock()
            if cached is not None and now < cached[0]:
                return deepcopy(cached[1])
            result = await self._fetch_models()
            self._cached = (now + self._cache_ttl_seconds, deepcopy(result))
            return result

    async def _fetch_models(self) -> BifrostCatalogueResponse:
        """Complete every page and body read under one wall-clock deadline."""

        try:
            async with asyncio.timeout(BIFROST_CATALOGUE_TIMEOUT_SECONDS):
                return await self._fetch_models_before_deadline()
        except TimeoutError:
            return unavailable("gateway_timeout")

    async def _fetch_models_before_deadline(self) -> BifrostCatalogueResponse:
        models_url, configuration_error = _models_url(self._base_url)
        if configuration_error is not None or models_url is None:
            return unavailable(configuration_error or "invalid_gateway_configuration")
        headers = _bearer_headers(self._key)
        if headers is None:
            return unavailable("invalid_gateway_configuration")

        models: list[BifrostModelView] = []
        seen: set[str] = set()
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        for _page_number in range(MAX_BIFROST_CATALOGUE_PAGES):
            try:
                status_code, body = await self._fetch_page(
                    _page_url(models_url, page_token),
                    headers,
                    BIFROST_CATALOGUE_TIMEOUT_SECONDS,
                    MAX_BIFROST_CATALOGUE_BODY_BYTES,
                )
            except (httpx.TimeoutException, TimeoutError):
                return unavailable("gateway_timeout")
            except _ResponseTooLarge:
                return unavailable("response_too_large")
            except _ResponseEncodingRejected:
                return unavailable("gateway_response_rejected")
            except httpx.HTTPError:
                return unavailable("gateway_unavailable")
            except Exception:
                return unavailable("gateway_unavailable")

            if type(status_code) is not int or not 100 <= status_code <= 599:
                return unavailable("gateway_response_rejected")
            if type(body) is not bytes:
                return unavailable("gateway_response_rejected")
            if 300 <= status_code < 400:
                return unavailable("gateway_redirect_rejected")
            if not 200 <= status_code < 300:
                return unavailable("gateway_response_rejected")
            if len(body) > MAX_BIFROST_CATALOGUE_BODY_BYTES:
                return unavailable("response_too_large")
            try:
                page_models, next_page_token = _page(body)
            except _SchemaInvalid:
                return unavailable("schema_invalid")

            if any(item["id"] in seen for item in page_models):
                return unavailable("schema_invalid")
            if len(models) + len(page_models) > MAX_BIFROST_CATALOGUE_MODELS:
                return unavailable("catalogue_too_large")
            models.extend(page_models)
            seen.update(item["id"] for item in page_models)

            if next_page_token is None:
                return {"status": "ok", "models": models, "reason": None}
            if not page_models or next_page_token in seen_page_tokens:
                return unavailable("schema_invalid")
            seen_page_tokens.add(next_page_token)
            page_token = next_page_token
        return unavailable("pagination_limit")


__all__ = [
    "BIFROST_CATALOGUE_PAGE_SIZE",
    "BIFROST_CATALOGUE_CACHE_TTL_SECONDS",
    "BIFROST_CATALOGUE_TIMEOUT_SECONDS",
    "MAX_BIFROST_CATALOGUE_BODY_BYTES",
    "MAX_BIFROST_CATALOGUE_MODELS",
    "MAX_BIFROST_CATALOGUE_PAGES",
    "BifrostCatalogueResponse",
    "BifrostModelCatalogue",
    "BifrostModelView",
    "CatalogueUnavailableReason",
    "PageFetcher",
    "unavailable",
]
