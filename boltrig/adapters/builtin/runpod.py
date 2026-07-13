"""Runpod pod controls as governed Boltrig verbs.

Docs basis: Runpod's REST API exposes pod listing plus start/stop/restart
operations under https://rest.runpod.io/v1/pods. Credentials stay kernel-side
and are presented only as an Authorization header for the duration of one call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import InvocationContext

Transport = Callable[[str, str, dict[str, str]], Awaitable[tuple[int, Any]]]

_BASE_URL = "https://rest.runpod.io/v1"


def _schema(required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"pod_id": {"type": "string"}},
        "required": required or [],
    }


def _token(credential: Credential | None) -> str | None:
    if credential is None:
        return None
    material = credential.material or {}
    for key in ("token", "api_key", "value"):
        value = material.get(key)
        if value:
            return str(value)
    return None


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


class RunpodAdapter:
    id = "runpod"
    version = "0.1.0"
    runtime = "http"
    source = "builtin"

    def __init__(
        self,
        *,
        base_url: str = _BASE_URL,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self.timeout = timeout

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

    async def execute(
        self, verb: str, params: dict[str, Any], credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        del context
        token = _token(credential)
        if not token:
            return Result.failure(AdapterError(ErrorClass.UNAUTHORISED, "runpod credential missing"))
        try:
            method, path = self._request(verb, params)
        except ValueError as exc:
            return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
        code, payload = await self._call(method, path, {"Authorization": f"Bearer {token}"})
        if code >= 400:
            return Result.failure(
                AdapterError(ErrorClass.UNAVAILABLE, f"runpod API returned {code}", retryable=True)
            )
        if verb == "runpod.pod.list":
            return Result.success({"pods": _pods(payload)})
        if verb == "runpod.pod.get":
            pod = _safe_pod(payload) if isinstance(payload, dict) else {}
            return Result.success({"pod": pod})
        return Result.success({"status_code": code, "pod_id": params["pod_id"], "action": verb})

    async def health(self) -> str:
        return "unknown"

    def _request(self, verb: str, params: dict[str, Any]) -> tuple[str, str]:
        if verb == "runpod.pod.list":
            return "GET", "/pods"
        if verb == "runpod.pod.get":
            return "GET", f"/pods/{params['pod_id']}"
        if verb == "runpod.pod.start":
            return "POST", f"/pods/{params['pod_id']}/start"
        if verb == "runpod.pod.stop":
            return "POST", f"/pods/{params['pod_id']}/stop"
        if verb == "runpod.pod.restart":
            return "POST", f"/pods/{params['pod_id']}/restart"
        raise ValueError(f"unknown verb {verb}")

    async def _call(
        self, method: str, path: str, headers: dict[str, str]
    ) -> tuple[int, Any]:
        if self._transport is not None:
            return await self._transport(method, path, headers)
        import httpx

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, self.base_url + path, headers=headers)
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            return response.status_code, payload


def build() -> RunpodAdapter:
    return RunpodAdapter()
