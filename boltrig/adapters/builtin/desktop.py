"""The desktop-hands adapter (source = 'builtin'), binding DH-1.

The familiar needs governed HANDS on the host desktop: list/focus/move/arrange
windows, switch workspaces, launch apps. The kernel runs in a container that
cannot reach the compositor's IPC socket, so the action cannot execute in-band.
Instead every verb here is dispatched as a COMMAND into the shared
``HandsRegistry`` (created once at boot, injected here); a host-side executor
pulls pending commands over the authenticated ``/v1/hands`` HTTP surface and
posts a receipt back. There is NO direct path from an agent to the desktop
(DH-1): the only writer of this registry is this handler, and it only ever runs
because the kernel dispatched a granted, schema-bound, audited call to it.

Doctrine mirrors familiar.express (decision 0014): the governed act is the
dispatch - grant-checked (SEC-07), schema-bound (SEC-21), audited (SEC-16).
Delivery to the host is best-effort: when no executor is polling, the verb still
dispatches and audits, and the result simply reports
``{status: "executor_offline", delivered: False}``.

Severability mirrors familiar.py: this module imports only
``boltrig.adapters.base`` + ``boltrig.models`` + stdlib. The registry is
injected, never imported, so the adapters layer stays independent of the kernel
transport.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import (
    AdapterError,
    Credential,
    ErrorClass,
    Result,
    VerbSpec,
)
from boltrig.models import InvocationContext

# How long a dispatch waits for the executor's receipt before reporting
# executor_offline. Deliberately shorter than the registry's command TTL (30 s)
# so a waiting dispatch always resolves before its command can be swept.
_DEFAULT_WAIT_S = 8.0

# Bounds for the window geometry the compositor is asked to apply. Width/height
# must be positive (a zero/negative rectangle is never a real window); x/y stay
# unbounded because multi-monitor layouts legitimately use negative origins.
_MAX_DIMENSION = 16384
_MAX_WORKSPACE = 64
_MAX_PLACEMENTS = 64
_MAX_EXEC_LEN = 1024

_HANDS_OUT = {
    "type": "object",
    "properties": {
        "status": {"type": "string"},
        "delivered": {"type": "boolean"},
        "result": {"type": "object"},
        "side_effects": {"type": "array"},
        "error": {"type": "string"},
    },
    "required": ["status", "delivered"],
    "additionalProperties": False,
}

_GEOMETRY = {
    "x": {"type": "integer"},
    "y": {"type": "integer"},
    "width": {"type": "integer", "minimum": 1, "maximum": _MAX_DIMENSION},
    "height": {"type": "integer", "minimum": 1, "maximum": _MAX_DIMENSION},
}

_RL_READ = {"per": "minute", "max": 120, "scope": "tenant"}
_RL_WRITE = {"per": "minute", "max": 60, "scope": "tenant"}


def _verb_specs() -> list[VerbSpec]:
    return [
        VerbSpec(
            verb_id="desktop.window.list",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="low",
            description="List the host desktop's windows (via the hands executor).",
            rate_limit=_RL_READ,
            # a pure read: replay-caching a window list is harmless
            idempotency_mode="cacheable",
        ),
        VerbSpec(
            verb_id="desktop.window.focus",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {"address": {"type": "string", "minLength": 1}},
                "required": ["address"],
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="low",
            description="Focus a host window by compositor address.",
            rate_limit=_RL_WRITE,
            # changes host state: never serve a focus from a replay cache (a
            # cached receipt would claim a delivery that did not happen)
            idempotency_mode="disabled",
        ),
        VerbSpec(
            verb_id="desktop.window.move",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {"address": {"type": "string", "minLength": 1}, **_GEOMETRY},
                "required": ["address", "x", "y", "width", "height"],
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="high",
            description="Move/resize a host window (visible, user-facing).",
            rate_limit=_RL_WRITE,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            verb_id="desktop.window.arrange",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {
                    "placements": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": _MAX_PLACEMENTS,
                        "items": {
                            "type": "object",
                            "properties": {
                                "address": {"type": "string", "minLength": 1},
                                **_GEOMETRY,
                            },
                            "required": ["address", "x", "y", "width", "height"],
                            "additionalProperties": False,
                        },
                    },
                    "preview": {"type": "boolean"},
                },
                "required": ["placements"],
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="high",
            description="Apply a multi-window layout on the host (preview optional).",
            rate_limit=_RL_WRITE,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            verb_id="desktop.workspace.switch",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_WORKSPACE,
                    }
                },
                "required": ["workspace"],
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="low",
            description="Switch the host desktop to a workspace.",
            rate_limit=_RL_WRITE,
            idempotency_mode="disabled",
        ),
        VerbSpec(
            verb_id="desktop.app.launch",
            noun_id="desktop",
            input_schema={
                "type": "object",
                "properties": {
                    "exec": {"type": "string", "minLength": 1, "maxLength": _MAX_EXEC_LEN}
                },
                "required": ["exec"],
                "additionalProperties": False,
            },
            output_schema=_HANDS_OUT,
            consequence="high",
            description="Launch an application on the host desktop.",
            rate_limit=_RL_WRITE,
            idempotency_mode="disabled",
        ),
    ]


class DesktopHandsAdapter:
    id = "desktop"
    version = "1.0.0"
    runtime = "file"

    def __init__(self, registry: Any, wait_seconds: float = _DEFAULT_WAIT_S) -> None:
        # The shared pending-command registry (HandsRegistry), injected so this
        # module never imports the kernel transport (severability, decision 0014).
        self._registry = registry
        self._wait_seconds = wait_seconds

    def describe(self) -> list[VerbSpec]:
        return _verb_specs()

    async def execute(
        self,
        verb: str,
        params: dict[str, Any],
        credential: Credential | None,
        context: InvocationContext,
    ) -> Result:
        known = {spec.verb_id for spec in _verb_specs()}
        if verb not in known:
            return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

        # The governed act happened the moment the kernel dispatched this call;
        # what remains is best-effort delivery. Enqueue the command and wait for
        # the executor's receipt.
        cmd = self._registry.create(verb, dict(params), context.run_id)
        receipt = await self._registry.wait(cmd["id"], self._wait_seconds)
        if receipt is None:
            # no executor polling (or it crashed): the dispatch is still audited,
            # delivery is just a no-op (same doctrine as familiar.express)
            return Result.success({"status": "executor_offline", "delivered": False})

        output: dict[str, Any] = {
            "status": receipt.get("status", "ok"),
            "delivered": True,
        }
        for key in ("result", "side_effects", "error"):
            if receipt.get(key) is not None:
                output[key] = receipt[key]
        return Result.success(output)

    async def health(self) -> str:
        return "ok"


def build(registry: Any, wait_seconds: float = _DEFAULT_WAIT_S) -> DesktopHandsAdapter:
    return DesktopHandsAdapter(registry, wait_seconds=wait_seconds)
