"""Reusable HTTP adapter base for ``runtime='http'`` integrations (S7.3).

Provides the cross-cutting machinery every REST integration needs so concrete
adapters (Microsoft Graph, Jira, generated OpenAPI adapters) stay thin:

  * retry with exponential backoff that honours ``Retry-After`` (NFR-REL),
  * cooperative client-side rate limiting (FR-KER-05),
  * link- and offset-based pagination iteration,
  * one mapping from HTTP status codes onto :class:`ErrorClass`
    (401/403 -> UNAUTHORISED, 404 -> NOT_FOUND, 409 -> CONFLICT,
    429 -> RATE_LIMITED with retry_after, 5xx -> UNAVAILABLE, 4xx -> INVALID).

Credentials arrive as a resolved :class:`Credential` for the duration of one
call (K-20, SEC-05). Material is turned into an ``Authorization`` header (or an
httpx auth object) and is never logged, never serialised into a :class:`Result`.

Subclasses set ``id`` / ``version``, implement :meth:`describe`, and register
per-verb handlers from :meth:`_handlers`. Handlers call :meth:`request`,
:meth:`paginate` or :meth:`paginate_offset`.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import email.utils
from typing import Any, AsyncIterator, Awaitable, Callable

import httpx

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.adapters.http_response import (
    MAX_JSON_RESPONSE_BYTES,
    ResponseBoundaryError,
    bounded_http_response,
    bounded_response_error,
)
from boltrig.adapters.http_policy import RateLimitConfig, RateLimiter, RetryPolicy
from boltrig.models import InvocationContext

# A per-verb handler: (params, authenticated client, context) -> Result.
Handler = Callable[
    [dict[str, Any], "httpx.AsyncClient", InvocationContext],
    Awaitable[Result],
]


class _HttpFailure(Exception):
    """Internal carrier so handlers can let a mapped error bubble to ``execute``."""

    def __init__(self, error: AdapterError) -> None:
        super().__init__(error.message)
        self.error = error


class HttpAdapter:
    """Base class for ``runtime='http'`` adapters (S7.3)."""

    runtime = "http"
    id = "http-adapter"
    version = "1.0.0"
    user_agent = "boltrig-httpadapter/1.0"
    requires_credential = True

    def __init__(
        self,
        *,
        base_url: str = "",
        timeout: float = 30.0,
        retry: RetryPolicy | None = None,
        rate_limit: RateLimitConfig | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retry = retry or RetryPolicy()
        self.rate_limit = rate_limit or RateLimitConfig()
        self._limiter = RateLimiter(self.rate_limit)
        self._default_headers = dict(default_headers or {})

    # --- contract surface ----------------------------------------------------
    def describe(self) -> list[VerbSpec]:
        raise NotImplementedError

    def _handlers(self) -> dict[str, Handler]:
        """Map verb id -> bound handler. Subclasses override."""
        return {}

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        handler = self._handlers().get(verb)
        if handler is None:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, f"unknown verb {verb}")
            )
        try:
            async with self._client(credential) as client:
                return await handler(params, client, context)
        except _HttpFailure as failure:
            return Result.failure(failure.error)
        except KeyError as missing:
            return Result.failure(
                AdapterError(ErrorClass.INVALID, f"missing parameter {missing}")
            )
        except httpx.HTTPError as exc:
            return Result.failure(self._map_transport_error(exc))
        except Exception as exc:  # a bad adapter must never crash the kernel (US-ADP-06)
            return Result.failure(
                AdapterError(ErrorClass.INTERNAL, f"adapter error: {type(exc).__name__}")
            )

    async def health(self) -> str:
        """Best-effort reachability probe. Never raises; needs no credential."""
        if not self.base_url:
            return "unknown"
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout, 5.0)) as client:
                async with client.stream(
                    "GET",
                    self.base_url,
                    headers={
                        "Accept-Encoding": "identity",
                        "User-Agent": self.user_agent,
                    },
                ) as resp:
                    return "ok" if resp.status_code < 500 else "degraded"
        except httpx.TimeoutException:
            return "degraded"
        except httpx.HTTPError:
            return "down"

    # --- helpers for subclasses ---------------------------------------------
    def base_url_for(self, credential: Credential | None) -> str:
        """Allow a per-tenant base URL to ride in on the credential material
        (e.g. each Jira site has its own host) without logging the material."""
        if credential is not None:
            override = credential.material.get("base_url")
            if isinstance(override, str) and override:
                return override.rstrip("/")
        return self.base_url

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        base = self.base_url_for(credential)
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        headers.update(self._default_headers)
        auth: httpx.Auth | None = None
        if credential is not None:
            extra, auth = self._auth(credential)
            headers.update(extra)
        # SSRF/rebinding (H2/SEC-61): pin the client's TCP target to the vetted IP
        # of the base host so httpx cannot re-resolve to internal space at connect
        # time. If the base host is internal (or empty), leave the client unpinned
        # and let the per-request egress guard in request() refuse it with INVALID.
        from boltrig.adapters.egress import EgressBlocked, pinned_transport

        transport: httpx.AsyncBaseTransport | None = None
        try:
            transport = pinned_transport(base)
        except EgressBlocked:
            transport = None
        return httpx.AsyncClient(
            base_url=base,
            headers=headers,
            timeout=self.timeout,
            auth=auth,
            # SSRF: never auto-follow redirects - a 302 to 169.254.169.254 would
            # bypass the pre-flight egress guard (CLOUD-03). A 3xx is returned to
            # the caller as-is instead of being chased into internal space.
            follow_redirects=False,
            transport=transport,
        )

    def _auth(
        self, credential: Credential
    ) -> tuple[dict[str, str], httpx.Auth | None]:
        """Turn credential material into request auth. Material is never logged
        (SEC-05): only the derived header/auth object leaves this method."""
        material = credential.material
        kind = credential.kind
        if kind == "basic":
            user = (
                material.get("username")
                or material.get("user")
                or material.get("email")
                or ""
            )
            secret = (
                material.get("password")
                or material.get("api_token")
                or material.get("token")
                or ""
            )
            return {}, httpx.BasicAuth(user, secret)
        token = (
            material.get("access_token")
            or material.get("token")
            or material.get("api_key")
        )
        if token:
            scheme = material.get("scheme", "Bearer")
            return {"Authorization": f"{scheme} {token}"}, None
        extra = material.get("headers")
        if isinstance(extra, dict):
            return {str(k): str(v) for k, v in extra.items()}, None
        return {}, None

    async def request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        content: bytes | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200, 201, 202, 204),
    ) -> dict[str, Any]:
        """A single REST call with retry/backoff, rate-limit cooperation and
        error mapping. Returns the parsed JSON body or raises :class:`_HttpFailure`."""
        # SSRF guard (INJ-02, CLOUD-03, SEC-61): refuse any target resolving to an
        # internal/non-routable address - private, loopback, link-local (incl.
        # 169.254.169.254 metadata), reserved - before the request leaves. Applies
        # to the effective URL (base_url join), so an agent-/generated-supplied path
        # cannot reach internal services or steal a managed-identity token. Combined
        # with follow_redirects=False, a redirect into internal space is also closed.
        from boltrig.adapters.egress import EgressBlocked, assert_egress_allowed

        try:
            assert_egress_allowed(str(client.base_url.join(url)))
        except EgressBlocked as exc:
            raise _HttpFailure(
                AdapterError(ErrorClass.INVALID, str(exc), retryable=False)
            ) from exc
        # Only idempotent verbs auto-retry: re-issuing a mutating call after a
        # transport error or a 5xx can duplicate a side effect that actually
        # landed (e.g. a dropped connection AFTER a successful email.send).
        idempotent = method.upper() in {"GET", "HEAD", "OPTIONS"}
        attempt = 0
        while True:
            attempt += 1
            await self._limiter.acquire()
            try:
                resp, _ = await bounded_http_response(
                    client,
                    method,
                    url,
                    max_bytes=MAX_JSON_RESPONSE_BYTES,
                    params=params,
                    json=json,
                    content=content,
                    data=data,
                    headers=headers,
                )
            except ResponseBoundaryError as exc:
                # A size/encoding refusal is deterministic for this response.
                # Retrying would spend the same bounded allocation again and can
                # amplify an upstream resource-exhaustion attempt.
                raise _HttpFailure(bounded_response_error()) from exc
            except httpx.HTTPError as exc:
                error = self._map_transport_error(exc)
                if idempotent and attempt < self.retry.max_attempts:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                raise _HttpFailure(error) from exc
            if resp.status_code in expected or 200 <= resp.status_code < 300:
                return self._parse(resp)
            error = self._map_status(resp)
            if error.retryable and idempotent and attempt < self.retry.max_attempts:
                delay = (
                    error.retry_after_seconds
                    if error.retry_after_seconds is not None
                    else self._backoff(attempt)
                )
                await asyncio.sleep(min(delay, self.retry.max_delay))
                continue
            raise _HttpFailure(error)

    async def paginate(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        items_key: str = "value",
        next_key: str = "@odata.nextLink",
        max_pages: int = 50,
    ) -> AsyncIterator[dict[str, Any]]:
        """Link-style pagination (Microsoft Graph ``@odata.nextLink`` and kin)."""
        next_url: str | None = url
        page = 0
        while next_url and page < max_pages:
            page += 1
            body = await self.request(client, "GET", next_url, params=params)
            for item in body.get(items_key) or []:
                yield item
            next_url = body.get(next_key)
            params = None  # the next link already carries its own query string

    async def paginate_offset(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        items_key: str = "values",
        start_key: str = "startAt",
        max_key: str = "maxResults",
        total_key: str = "total",
        page_size: int = 50,
        max_pages: int = 50,
    ) -> AsyncIterator[dict[str, Any]]:
        """Offset-style pagination (Jira ``startAt`` / ``maxResults`` and kin)."""
        query = dict(params or {})
        start = int(query.get(start_key, 0))
        query[max_key] = page_size
        page = 0
        while page < max_pages:
            page += 1
            query[start_key] = start
            body = await self.request(client, "GET", url, params=query)
            items = body.get(items_key) or []
            for item in items:
                yield item
            if not items:
                break
            start += len(items)
            total = body.get(total_key)
            if total is not None and start >= int(total):
                break

    # --- error mapping -------------------------------------------------------
    def _map_status(self, resp: httpx.Response) -> AdapterError:
        code = resp.status_code
        if code in (401, 403):
            return AdapterError(ErrorClass.UNAUTHORISED, f"http {code}", retryable=False)
        if code == 404:
            return AdapterError(ErrorClass.NOT_FOUND, "http 404", retryable=False)
        if code == 409:
            return AdapterError(ErrorClass.CONFLICT, "http 409", retryable=False)
        if code == 429:
            retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
            return AdapterError(
                ErrorClass.RATE_LIMITED,
                "http 429",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if 500 <= code <= 599:
            retry_after = self._parse_retry_after(resp.headers.get("Retry-After"))
            return AdapterError(
                ErrorClass.UNAVAILABLE,
                f"http {code}",
                retryable=True,
                retry_after_seconds=retry_after,
            )
        if 400 <= code <= 499:
            return AdapterError(ErrorClass.INVALID, f"http {code}", retryable=False)
        return AdapterError(ErrorClass.INTERNAL, f"unexpected http {code}", retryable=False)

    def _map_transport_error(self, exc: httpx.HTTPError) -> AdapterError:
        # Backend unreachable / timed out -> unavailable (may trigger degraded mode, P9).
        return AdapterError(
            ErrorClass.UNAVAILABLE,
            f"transport error: {type(exc).__name__}",
            retryable=True,
        )

    def _backoff(self, attempt: int) -> float:
        delay = self.retry.base_delay * (self.retry.backoff_factor ** (attempt - 1))
        return min(delay, self.retry.max_delay)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        """Honour ``Retry-After`` as either delta-seconds or an HTTP-date."""
        if not value:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
        try:
            when = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        now = _dt.datetime.now(when.tzinfo) if when.tzinfo else _dt.datetime.now()
        delta = (when - now).total_seconds()
        return delta if delta > 0 else 0.0

    @staticmethod
    def _parse(resp: httpx.Response) -> dict[str, Any]:
        if resp.status_code == 204 or not resp.content:
            return {}
        ctype = resp.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                data = resp.json()
            except ValueError:
                return {"text": resp.text}
            return data if isinstance(data, dict) else {"items": data}
        return {"text": resp.text}
