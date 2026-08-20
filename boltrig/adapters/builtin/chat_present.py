"""The non-mutating ``chat.present`` tool for validated display objects."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import InvocationContext
from boltrig.models.display_object_schema import display_object_input_schema
from boltrig.models.display_objects import (
    DISPLAY_OBJECT_KINDS,
    DisplayObjectValidationError,
    build_display_object,
)


class ChatPresentAdapter:
    id = "chat-present"
    version = "1.0.0"
    runtime = "script"

    def __init__(self, events: Any = None) -> None:
        self._events = events

    def describe(self) -> list[VerbSpec]:
        return [
            VerbSpec(
                verb_id="chat.present",
                noun_id="chat",
                input_schema=display_object_input_schema(DISPLAY_OBJECT_KINDS),
                output_schema={
                    "type": "object",
                    "properties": {
                        "object_id": {"type": "string"},
                        "kind": {"type": "string"},
                        "status": {"type": "string"},
                    },
                    "required": ["object_id", "kind", "status"],
                },
                consequence="low",
                description=(
                    "Render one validated chat card from the closed Boltrig template catalogue. "
                    "Use custom.card only with reviewed blocks; never emit HTML, JSX or JavaScript."
                ),
                idempotency_mode="disabled",
            )
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        del credential
        if verb != "chat.present":
            return Result.failure(AdapterError(ErrorClass.INVALID, "unknown chat presentation verb"))
        target_run = context.parent_run_id or context.run_id
        if (
            context.actor_tier != "tier1"
            or not target_run
            or not isinstance(context.extra.get("conversation_id"), str)
        ):
            return Result.failure(
                AdapterError(ErrorClass.UNAUTHORISED, "display objects require an interactive named-agent turn")
            )
        try:
            display_object = build_display_object(
                params, run_id=target_run, agent_address=context.actor
            )
        except DisplayObjectValidationError:
            return Result.failure(AdapterError(ErrorClass.INVALID, "display object is invalid"))
        if self._events is None:
            return Result.failure(AdapterError(ErrorClass.UNAVAILABLE, "chat presentation relay unavailable"))
        self._events.publish(
            context.tenant_id,
            target_run,
            {"type": "display_object", "run_id": target_run, "object": display_object},
        )
        return Result.success(
            {"object_id": display_object["id"], "kind": display_object["kind"], "status": "presented"}
        )

    async def health(self) -> str:
        return "ok"


def build(*, events: Any = None) -> ChatPresentAdapter:
    return ChatPresentAdapter(events=events)


__all__ = ["ChatPresentAdapter", "build"]
