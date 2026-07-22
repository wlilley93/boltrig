"""Runpod pod controls as governed Boltrig verbs.

Docs basis: Runpod's REST API exposes pod listing plus start/stop/restart
operations under https://rest.runpod.io/v1/pods. Credentials stay kernel-side
and are presented only as an Authorization header for the duration of one call.

Built on :class:`HttpAdapter` (S7.3): HTTP status -> ErrorClass mapping, retry/
backoff (idempotent reads only), cooperative rate limiting and egress pinning
all come from the base; this module carries only the verb surface, the bearer
convention and payload redaction.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
    bearer_token,
)
from boltrig.adapters.http_base import Handler, HttpAdapter
from boltrig.models import InvocationContext

_BASE_URL = "https://rest.runpod.io/v1"


def _schema(required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"pod_id": {"type": "string"}},
        "required": required or [],
    }


def _safe_pod(raw: dict[str, Any]) -> dict[str, Any]:
    machine = raw.get("machine") if isinstance(raw.get("machine"), dict) else {}
    gpu = raw.get("gpu") if isinstance(raw.get("gpu"), dict) else {}
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "desiredStatus": raw.get("desiredStatus"),
        "lastStartedAt": raw.get("lastStartedAt"),
        "lastStatusChange": raw.get("lastStatusChange"),
        "costPerHr": raw.get("costPerHr"),
        "adjustedCostPerHr": raw.get("adjustedCostPerHr"),
        "gpu": {"id": gpu.get("id"), "displayName": gpu.get("displayName")},
        "machine": {
            "machineId": machine.get("machineId"),
            "vcpuCount": machine.get("vcpuCount"),
            "memoryInGb": machine.get("memoryInGb"),
        },
    }


def _pods(payload: Any) -> list[dict[str, Any]]:
    raw = payload.get("pods", payload) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    return [_safe_pod(item) for item in raw if isinstance(item, dict)]


class RunpodAdapter(HttpAdapter):
    id = "runpod"
    version = "0.1.0"
    source = "builtin"
    user_agent = "boltrig-runpod/1.0"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        self._transport = transport

    def describe(self) -> list[VerbSpec]:
        any_out = {"type": "object"}
        return [
            VerbSpec("runpod.pod.list", "runpod", _schema(), any_out, "low",
                     "List Runpod pods with redacted metadata."),
            VerbSpec("runpod.pod.get", "runpod", _schema(["pod_id"]), any_out, "low",
                     "Read one Runpod pod with redacted metadata."),
            VerbSpec("runpod.pod.start", "runpod", _schema(["pod_id"]), any_out, "high",
                     "Start or resume a Runpod pod."),
            VerbSpec("runpod.pod.stop", "runpod", _schema(["pod_id"]), any_out, "high",
                     "Stop a Runpod pod."),
            VerbSpec("runpod.pod.restart", "runpod", _schema(["pod_id"]), any_out, "high",
                     "Restart a Runpod pod."),
        ]

    def _handlers(self) -> dict[str, Handler]:
        return {
            "runpod.pod.list": self._pod_list,
            "runpod.pod.get": self._pod_get,
            "runpod.pod.start": self._pod_start,
            "runpod.pod.stop": self._pod_stop,
            "runpod.pod.restart": self._pod_restart,
        }

    async def execute(
        self, verb: str, params: dict[str, Any], credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        # Fail closed: never post an empty bearer (SEC-04/05).
        if bearer_token(credential) is None:
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "runpod credential missing")
            )
        return await super().execute(verb, params, credential, context)

    def _auth(self, credential: Credential) -> tuple[dict[str, str], httpx.Auth | None]:
        token = bearer_token(credential)
        if token:
            return {"Authorization": f"Bearer {token}"}, None
        return {}, None

    def _client(self, credential: Credential | None) -> httpx.AsyncClient:
        if self._transport is None:
            return super()._client(credential)
        # Injected transport (tests): same headers/auth, no egress pinning.
        base = self.base_url_for(credential)
        headers: dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }
        auth: httpx.Auth | None = None
        if credential is not None:
            extra, auth = self._auth(credential)
            headers.update(extra)
        return httpx.AsyncClient(
            base_url=base,
            headers=headers,
            timeout=self.timeout,
            auth=auth,
            follow_redirects=False,
            transport=self._transport,
        )

    async def health(self) -> str:
        return "unknown"

    # --- handlers ------------------------------------------------------------
    async def _pod_list(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        data = await self.request(client, "GET", "/pods")
        return Result.success({"pods": _pods(data.get("items", data))})

    async def _pod_get(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        data = await self.request(client, "GET", f"/pods/{_pod_id(params)}")
        return Result.success({"pod": _safe_pod(data) if isinstance(data, dict) else {}})

    async def _pod_start(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        return await self._pod_action("start", params, client)

    async def _pod_stop(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        return await self._pod_action("stop", params, client)

    async def _pod_restart(
        self, params: dict[str, Any], client: httpx.AsyncClient, context: InvocationContext
    ) -> Result:
        return await self._pod_action("restart", params, client)

    async def _pod_action(
        self, action: str, params: dict[str, Any], client: httpx.AsyncClient
    ) -> Result:
        await self.request(client, "POST", f"/pods/{_pod_id(params)}/{action}")
        return Result.success({"pod_id": params["pod_id"], "action": f"runpod.pod.{action}"})


def _pod_id(params: dict[str, Any]) -> str:
    # URL-quoted: a pod id with '/', '?' or '..' must not rewrite the path.
    return quote(str(params["pod_id"]), safe="")


def build() -> RunpodAdapter:
    return RunpodAdapter()
