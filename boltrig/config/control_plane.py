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

Beat 3.5 (control-plane verb parity, SEC-75/76/77) extends the same pattern to
the remaining console authoring operations - skills, nouns, verbs, bindings,
external MCP-server registration and manifest-section config - so a chat-driven
agent can perform every authoring operation THROUGH the chokepoint. The direct
author-gated routes stay for the UI; route and verb call the same module-level
write helper per noun below, so the two paths cannot drift. MCP-server
ACTIVATION deliberately has no verb: a registered consumer stays inert until the
SEC-22 human review route activates it.

The adapter performs the store write inside ``execute`` only; it owns no policy of
its own (P1). It imports only adapter base + models (the MCP consumer lazily);
it does not import the kernel, so it stays severable.
"""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import AdapterError, Credential, ErrorClass, Result, VerbSpec
from boltrig.models import (
    AgentCapability,
    Consequence,
    InvocationContext,
    ModelEndpoint,
    Noun,
    Skill,
    TargetType,
    Verb,
    VerbBinding,
    WorkflowDefinition,
    WorkflowSource,
)

_OBJ: dict = {"type": "object"}


# --- safe-by-default consequence for authored verbs (SEC-39) ------------------
# Verb-name tokens that imply a mutating / destructive / outbound effect. A verb
# authored with such a name and no explicit consequence defaults to high, so the
# HITL gate engages by default (US-RTR-02/04, SEC-39: safe-by-default authoring).
_DESTRUCTIVE_TOKENS: frozenset[str] = frozenset({
    "delete", "remove", "destroy", "drop", "purge", "wipe", "erase",
    "send", "email", "post", "pay", "transfer", "charge", "refund",
    "deactivate", "revoke", "cancel", "terminate", "approve", "publish",
})


def safe_consequence(verb_id: str, explicit) -> str:
    """The consequence to store for an authored verb. An explicit low/high is
    honoured; otherwise a destructive/outbound verb name defaults to high (SEC-39)."""
    if explicit in ("low", "high"):
        return explicit
    tail = verb_id.rsplit(".", 1)[-1].lower()
    return "high" if any(tok in tail for tok in _DESTRUCTIVE_TOKENS) else "low"


# --- the single write path per authoring noun (Beat 3.5, SEC-75) --------------
# One helper per noun, called by BOTH the direct author-gated route
# (kernel/platform_routes.py) and the governed control.* verb below, so the two
# write paths are one and cannot drift.
async def upsert_skill_record(store: Any, tenant_id: str, params: dict) -> Skill:
    """Build + upsert a Skill from an authoring payload (route + verb parity)."""
    skill = Skill(
        id=params["id"], tenant_id=tenant_id, version=params.get("version", "1.0.0"),
        prompt_fragment=params.get("prompt_fragment", ""),
        tool_grants=params.get("tool_grants", []),
        context_requirements=params.get("context_requirements", {}),
        extends=params.get("extends"), locale=params.get("locale", "en"),
    )
    await store.upsert_skill(skill)
    return skill


async def upsert_noun_record(store: Any, tenant_id: str, params: dict) -> Noun:
    """Build + upsert a Noun from an authoring payload (route + verb parity)."""
    noun = Noun(id=params["id"], tenant_id=tenant_id,
                description=params.get("description", ""),
                schema=params.get("schema", {}))
    await store.upsert_noun(noun)
    return noun


async def upsert_verb_record(store: Any, tenant_id: str, params: dict) -> Verb:
    """Build + upsert a Verb, applying the safe-by-default consequence (SEC-39)."""
    conseq = safe_consequence(params["id"], params.get("consequence"))
    verb = Verb(
        id=params["id"], tenant_id=tenant_id, noun_id=params["noun_id"],
        input_schema=params.get("input_schema", {}),
        output_schema=params.get("output_schema", {}),
        description=params.get("description", ""),
        consequence=Consequence(conseq),
    )
    await store.upsert_verb(verb)
    return verb


async def set_binding_record(store: Any, tenant_id: str, verb_id: str, params: dict) -> VerbBinding:
    """Build + upsert a VerbBinding (route + verb parity). Raises ValueError on
    an unknown target_type (fail-closed)."""
    binding = VerbBinding(
        verb_id=verb_id, tenant_id=tenant_id,
        target_type=TargetType(params["target_type"]), target_ref=params["target_ref"],
    )
    await store.upsert_binding(binding)
    return binding


def register_mcp_consumer(loader: Any, tenant_id: str, params: dict) -> Any:
    """Register an external MCP server as a consumer adapter, INERT pending the
    SEC-22 human review (route + verb parity). Returns the consumer."""
    from boltrig.adapters.mcp_consumer import McpConsumerAdapter

    consumer = McpConsumerAdapter(
        params["id"], url=params.get("url"), token=params.get("token")
    )
    loader.register(tenant_id, consumer)  # inert pending review (SEC-22)
    return consumer


class ControlPlaneAdapter:
    """Config amendment as governed verbs (``control.*``)."""

    id = "control"
    version = "0.1.0"
    runtime = "script"
    source = "builtin"

    def __init__(self, store: Any, *, loader: Any = None, admin: Any = None) -> None:
        self._store = store
        # Optional collaborators for the Beat 3.5 verbs; injected as plain objects
        # so the adapter never imports the kernel. Absent, the affected verb
        # returns a typed "unavailable" result rather than crashing (P9).
        self._loader = loader  # the kernel AdapterLoader (control.mcp_server.register)
        self._admin = admin  # the platform AdminConfig (control.config.upsert)

    def set_admin(self, admin: Any) -> None:
        """Late-bind the platform's ONE AdminConfig (built after the kernel), so
        the PUT route and control.config.upsert mutate one config doc (SEC-75)."""
        self._admin = admin

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
            # --- Beat 3.5: the remaining console authoring operations (SEC-75) ---
            VerbSpec(
                verb_id="control.skill.upsert", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "version": {"type": "string"},
                        "prompt_fragment": {"type": "string"},
                        "tool_grants": {"type": "array", "items": {"type": "string"}},
                        "context_requirements": {"type": "object"},
                        "extends": {"type": "string"}, "locale": {"type": "string"},
                    },
                    "required": ["id"]},
                output_schema=_OBJ, consequence="high",
                description="Author/replace a skill (governed)"),
            VerbSpec(
                verb_id="control.noun.define", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "description": {"type": "string"},
                        "schema": {"type": "object"},
                    },
                    "required": ["id"]},
                output_schema=_OBJ, consequence="high",
                description="Define/replace a noun (governed)"),
            VerbSpec(
                verb_id="control.verb.define", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"}, "noun_id": {"type": "string"},
                        "input_schema": {"type": "object"}, "output_schema": {"type": "object"},
                        "description": {"type": "string"}, "consequence": {"type": "string"},
                    },
                    "required": ["id", "noun_id"]},
                output_schema=_OBJ, consequence="high",
                description="Define/replace a verb, safe-by-default consequence (governed)"),
            VerbSpec(
                verb_id="control.binding.set", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {
                        "verb_id": {"type": "string"},
                        "target_type": {"type": "string", "enum": ["adapter", "agent"]},
                        "target_ref": {"type": "string"},
                    },
                    "required": ["verb_id", "target_type", "target_ref"]},
                output_schema=_OBJ, consequence="high",
                description="Point a verb at an adapter or a reasoning agent (governed)"),
            VerbSpec(
                verb_id="control.mcp_server.register", noun_id="control",
                # No token/credential property, and none accepted: a secret in verb
                # params would surface on the run event stream (SEC-27). A
                # token-bearing registration uses the author route or the manifest's
                # ${ENV} interpolation. The consumer registers INERT; activation
                # stays on the SEC-22 human review route - there is NO verb for it.
                input_schema={
                    "type": "object",
                    "properties": {"id": {"type": "string"}, "url": {"type": "string"}},
                    "required": ["id"], "additionalProperties": False},
                output_schema=_OBJ, consequence="high",
                description="Register an external MCP server, inert until human review (governed)"),
            VerbSpec(
                verb_id="control.config.upsert", noun_id="control",
                input_schema={
                    "type": "object",
                    "properties": {"section": {"type": "string"}, "value": {}},
                    "required": ["section", "value"]},
                output_schema=_OBJ, consequence="high",
                description="Update a manifest config section, revision-recorded (governed)"),
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
        # --- Beat 3.5: console authoring parity, one write path per noun (SEC-75)
        if verb == "control.skill.upsert":
            skill = await upsert_skill_record(self._store, tenant, params)
            return Result.success({"upserted": "skill", "id": skill.id, "version": skill.version})
        if verb == "control.noun.define":
            noun = await upsert_noun_record(self._store, tenant, params)
            return Result.success({"upserted": "noun", "id": noun.id})
        if verb == "control.verb.define":
            vdef = await upsert_verb_record(self._store, tenant, params)
            return Result.success({"upserted": "verb", "id": vdef.id,
                                   "consequence": vdef.consequence.value})
        if verb == "control.binding.set":
            try:
                binding = await set_binding_record(
                    self._store, tenant, params["verb_id"], params
                )
            except ValueError as exc:  # unknown target_type: typed, fail-closed
                return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
            return Result.success({"upserted": "binding", "verb": binding.verb_id,
                                   "target": binding.target_ref})
        if verb == "control.mcp_server.register":
            if self._loader is None:
                return Result.failure(
                    AdapterError(ErrorClass.UNAVAILABLE, "adapter loader not wired")
                )
            # by-reference only: never pass a secret through verb-space (SEC-27)
            consumer = register_mcp_consumer(
                self._loader, tenant, {"id": params["id"], "url": params.get("url")}
            )
            return Result.success({"registered": "mcp_server", "id": consumer.id,
                                   "activated": False})
        if verb == "control.config.upsert":
            if self._admin is None:
                return Result.failure(
                    AdapterError(ErrorClass.UNAVAILABLE, "admin config not wired")
                )
            try:
                rev = await self._admin.update_section(
                    params["section"], params.get("value"), context.actor
                )
            except ValueError as exc:  # e.g. a null section value
                return Result.failure(AdapterError(ErrorClass.INVALID, str(exc)))
            return Result.success({"upserted": "config", "section": params["section"],
                                   "revision": rev.id})
        return Result.failure(AdapterError(ErrorClass.INVALID, f"unknown verb {verb}"))

    async def health(self) -> str:
        return "ok"


def build_control_plane_adapter(
    store: Any, *, loader: Any = None, admin: Any = None
) -> ControlPlaneAdapter:
    """Construct the control-plane adapter for registration in bootstrap."""
    return ControlPlaneAdapter(store, loader=loader, admin=admin)
