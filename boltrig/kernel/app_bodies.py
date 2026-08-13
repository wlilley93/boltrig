"""The typed request bodies the kernel HTTP door accepts.

Their own module because they are the door's PUBLIC CONTRACT - what a caller or an
SDK may send - and reading them should not mean paging through route wiring.
``app.py`` sits at a structural ratchet, and a contract that grows when the
product grows should not be spending that budget.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from boltrig.model_choice_policy import opaque_model_choice_id


class InvokeBody(BaseModel):
    noun: str
    verb: str
    params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None
    # OPTIONAL channel label: WHICH SURFACE this turn arrived through, so one
    # conversation can span two of them (a message typed into an Opbox spotlight
    # and the same thread in the boltrig UI) and still say where each turn came
    # from. It is a LABEL and reaches no authority or routing decision - see
    # fleet/chat_origin for why this is deliberately NOT WorkItem.source, which
    # selects the handling department. Unusable values are dropped, never a
    # reason to refuse someone's message. Absent => today's behaviour (NULL).
    origin: str | None = None
    approval_id: str | None = None


class SpawnBody(BaseModel):
    task: str
    skills: list[str] = Field(default_factory=list)
    prefer: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class RespondBody(BaseModel):
    decision: str
    notes: str = ""


class ChatBody(BaseModel):
    message: str
    conversation_id: str | None = None
    # Inline, size-capped attachments ([2026] VJS-COUNTY 3): each is a record
    # {name, media_type, data (base64)}. Caps are enforced fail-closed at intake
    # from ChatConfig; an over-cap turn is refused whole before anything persists.
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # OPTIONAL permission-parity passthrough: a caller's clamped external bearer
    # (e.g. the opbox-kernel session bearer, already clamped to min(agent,user))
    # that the fleet seals per-run for the opbox adapter, so a downstream service
    # call enforces the CALLER's grants rather than the adapter's static service
    # token. Absent => today's behaviour (static adapter credential). This is a
    # CALLER-supplied downstream credential, NOT an identity override: the PAT's
    # user is still the chatter and every spawn is still ceilinged by their grants.
    on_behalf_bearer: str | None = None
    # OPTIONAL exactly-once key for THIS user message, chosen by the client.
    # A retry that reuses it is answered as an accepted replay instead of
    # convening a second agent: measured on a live tenant, one message sent five
    # times 1.4-2.1s apart produced seven agent_spawn rows. SpawnBody has carried
    # one since SEC-15; the surface a person actually types into had none.
    # Absent => today's behaviour exactly (see fleet/chat_idempotency).
    idempotency_key: str | None = None
    # OPTIONAL channel label: WHICH SURFACE this turn arrived through, so one
    # conversation can span two of them (a message typed into an Opbox spotlight
    # and the same thread in the boltrig UI) and still say where each turn came
    # from. It is a LABEL and reaches no authority or routing decision - see
    # fleet/chat_origin for why this is deliberately NOT WorkItem.source, which
    # selects the handling department. Unusable values are dropped, never a
    # reason to refuse someone's message. Absent => today's behaviour (NULL).
    origin: str | None = None
    # Optional caller preference among administrator-approved profiles. It is a
    # request, never authority: the runtime resolver looks it up only in
    # server-held profile data and residency/availability policy may override it.
    model_profile_id: str | None = None
    # Opaque tenant-approved text-chat choice. The runtime resolves this id from
    # the tenant store; no caller-supplied model name or provider route is used.
    model_choice_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        pattern=r"^[!-~]+$",
    )

    @field_validator("model_choice_id")
    @classmethod
    def _valid_model_choice_id(cls, value: str | None) -> str | None:
        return None if value is None else opaque_model_choice_id(value)
