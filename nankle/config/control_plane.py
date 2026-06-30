"""The ControlPlaneAdapter: governed config amendment behind the chokepoint.

Round Seven, governance requirement 5.1. Today the control-plane writes (author a
workflow, a capability, a model endpoint) are direct ``store.upsert_*`` calls from
author-gated HTTP routes - a second, ungoverned write path, which is exactly what
P2 (one dispatch chokepoint) rules out.

This adapter makes those amendments normal kernel verbs. Because it is a plain
adapter (the MemoryAdapter pattern), every amendment runs the unchanged dispatch
sequence: schema validation, **grant check**, the **consequence/HITL gate**,
idempotency, and **audit** - the same guarantees as any other action, for free
(SEC-51). Config mutation is high-blast, so the verbs are ``consequence="high"``:
the HITL gate can hold a config change for approval exactly as it holds any other
high-consequence action.

The adapter performs the store write inside ``execute`` only; it owns no policy of
its own (P1). It imports only adapter base + models; it does not import the
kernel, so it stays severable.
"""

from __future__ import annotations

from typing import Any

from nankle.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from nankle.models import (
    AgentCapability,
    InvocationContext,
    ModelEndpoint,
    WorkflowDefinition,
    WorkflowSource,
)

_OBJ: dict = {"type": "object"}


class ControlPlaneAdapter:
    """Config amendment as governed verbs (``control.*``)."""

    id = "control"
    version = "0.1.0"
    runtime = "script"
    source = "builtin"

    def __init__(self, store: Any) -> None:
        self._store = store

    def describe(self) -> list[VerbSpec]:
        # All high-consequence: a config amendment is high-blast, so the HITL gate
        # can hold it for approval like any other high-consequence action (5.1).
        return [
            VerbSpec(
                verb_id="control.workflow.upsert", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "version": {"type": "string"},
                        "source": {"type": "string"}, "definition": {"type": "object"},
                        "intent_tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["id"]},
                output_schema=_OBJ, consequence="high",
                description="Author/replace a workflow definition (governed)"),
            VerbSpec(
                verb_id="control.capability.upsert", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"}, "runtime": {"type": "string"},
                        "supported_skills": {"type": "array", "items": {"type": "string"}},
                        "max_depth": {"type": "integer"}, "is_ephemeral": {"type": "boolean"},
                        "cost_tier": {"type": "string"}, "model_endpoint": {"type": "string"},
                    },
                    "required": ["name", "runtime"]},
                output_schema=_OBJ, consequence="high",
                description="Author/replace an agent capability profile (governed)"),
            VerbSpec(
                verb_id="control.model_endpoint.upsert", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "kind": {"type": "string"},
                        "model": {"type": "string"}, "base_url": {"type": "string"},
                        "fallback": {"type": "string"}, "data_class": {"type": "string"},
                    },
                    "required": ["id", "kind", "model"]},
                output_schema=_OBJ, consequence="high",
                description="Author/replace a model endpoint, incl. the gateway base_url (governed)"),
        ]

    async def execute(
        self, verb: str, params: dict, credential: Credential | None, context: InvocationContext
    ) -> Result:
        tenant = context.tenant_id
        if verb == "control.workflow.upsert":
            wf = WorkflowDefinition(
                id=params["id"], tenant_id=tenant, version=params.get("version", "1.0.0"),
                source=WorkflowSource(params.get("source", "precreated")),
                definition=params.get("definition", {}), intent_tags=params.get("intent_tags", []),
            )
            await self._store.upsert_workflow(wf)
            return Result.success({"upserted": "workflow", "id": wf.id})
        if verb == "control.capability.upsert":
            cap = AgentCapability(
                name=params["name"], tenant_id=tenant, runtime=params["runtime"],
                supported_skills=params.get("supported_skills", ["*"]),
                max_depth=int(params.get("max_depth", 1)),
                is_ephemeral=bool(params.get("is_ephemeral", True)),
                cost_tier=params.get("cost_tier", "standard"),
                model_endpoint=params.get("model_endpoint"),
            )
            await self._store.upsert_capability(cap)
            return Result.success({"upserted": "capability", "id": cap.name})
        if verb == "control.model_endpoint.upsert":
            ep = ModelEndpoint(
                id=params["id"], tenant_id=tenant, kind=params["kind"], model=params["model"],
                base_url=params.get("base_url"), fallback=params.get("fallback"),
                data_class=params.get("data_class", "standard"),
            )
            await self._store.upsert_model_endpoint(ep)
            return Result.success({"upserted": "model_endpoint", "id": ep.id})
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return "ok"


def build_control_plane_adapter(store: Any) -> ControlPlaneAdapter:
    """Construct the control-plane adapter for registration in bootstrap."""
    return ControlPlaneAdapter(store)
