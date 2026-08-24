"""HTTP adapter error mapping (arc-1 structural partial).

The status-code -> :class:`ErrorClass` mapping, transport-error mapping, retry
backoff and response parsing extracted verbatim from
``boltrig/adapters/http_base.py`` as a mixin. ``HttpAdapter`` composes it;
the method surface on the final class is unchanged.

Host contract: uses ``self.retry`` (a ``RetryPolicy`` set by HttpAdapter).
"""

from __future__ import annotations

import datetime as _dt
import email.utils
from typing import Any

import httpx

from boltrig.adapters.base import AdapterError, ErrorClass


class HttpErrorMappingMixin:
    """Error mapping + retry/backoff helpers for ``HttpAdapter``."""

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
