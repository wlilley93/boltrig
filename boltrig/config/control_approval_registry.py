"""Authored skill, noun, verb and binding approval fingerprints."""

from __future__ import annotations

from typing import Any

from boltrig.models import AdapterFailure, InvocationContext

from .control_approval_workflows import model_endpoint_view

AUTHORED_DEFINITION_ACTIONS = frozenset(
    {
        "control.skill.archive",
        "control.skill.restore",
        "control.noun.archive",
        "control.noun.restore",
        "control.verb.archive",
        "control.verb.restore",
    }
)


def _skill_view(skill: Any) -> dict[str, Any] | None:
    if skill is None:
        return None
    return {
        "id": skill.id,
        "version": skill.version,
        "prompt_fragment": skill.prompt_fragment,
        "tool_grants": skill.tool_grants,
        "context_requirements": skill.context_requirements,
        "extends": skill.extends,
        "locale": skill.locale,
        "description": skill.description,
        "is_active": skill.is_active,
    }


def _noun_view(noun: Any) -> dict[str, Any] | None:
    if noun is None:
        return None
    return {
        "id": noun.id,
        "description": noun.description,
        "schema": noun.schema,
        "is_active": noun.is_active,
    }


def _binding_view(binding: Any) -> dict[str, Any] | None:
    if binding is None:
        return None
    return {
        "verb_id": binding.verb_id,
        "target_type": binding.target_type.value,
        "target_ref": binding.target_ref,
        "rate_limit": (
            {
                "per": binding.rate_limit.per,
                "max": binding.rate_limit.max,
                "scope": binding.rate_limit.scope,
            }
            if binding.rate_limit
            else None
        ),
    }


def _verb_view(verb: Any) -> dict[str, Any] | None:
    if verb is None:
        return None
    return {
        "id": verb.id,
        "noun_id": verb.noun_id,
        "input_schema": verb.input_schema,
        "output_schema": verb.output_schema,
        "description": verb.description,
        "consequence": verb.consequence.value,
        "degraded_mode": verb.degraded_mode,
        "identity_mode": verb.identity_mode,
        "idempotency_mode": verb.idempotency_mode.value,
        "is_active": verb.is_active,
    }


async def skill_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    skill_id = str(params["id"])
    skill = await store.get_skill_any(context.tenant_id, skill_id)
    if skill is None:
        raise AdapterFailure(
            "skill not found", status_code=404, reason="control_resource_not_found"
        )
    children = sorted(
        (
            {"id": item.id, "version": item.version, "is_active": item.is_active}
            for item in await store.list_all_skills(context.tenant_id)
            if item.extends == skill_id
        ),
        key=lambda item: item["id"],
    )
    return {"skill": _skill_view(skill), "children": children}


async def skill_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    skill_id = str(params["id"])
    current = await store.get_skill_any(context.tenant_id, skill_id)
    parent_id = str(params.get("extends") or "").strip() or None
    parent = (
        await store.get_skill_any(context.tenant_id, parent_id)
        if parent_id
        else None
    )
    if parent_id and parent is None:
        raise AdapterFailure(
            "parent skill not found",
            status_code=404,
            reason="control_resource_not_found",
        )
    if (
        parent is not None
        and not parent.is_active
        and (current is None or current.extends != parent_id)
    ):
        raise AdapterFailure(
            "parent skill is archived",
            status_code=409,
            reason="authored_definition_inactive",
        )
    return {"skill": _skill_view(current), "parent": _skill_view(parent)}


async def noun_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    noun_id = str(params["id"])
    noun = await store.get_noun_any(context.tenant_id, noun_id)
    if noun is None:
        raise AdapterFailure(
            "noun not found", status_code=404, reason="control_resource_not_found"
        )
    if noun_id == "control":
        raise AdapterFailure(
            "the control noun is protected",
            status_code=409,
            reason="control_resource_protected",
        )
    verbs = []
    for verb in sorted(
        await store.list_all_verbs(context.tenant_id, noun_id),
        key=lambda item: item.id,
    ):
        verbs.append(
            {
                "definition": _verb_view(verb),
                "binding": _binding_view(
                    await store.get_binding(context.tenant_id, verb.id)
                ),
            }
        )
    return {"noun": _noun_view(noun), "verbs": verbs}


async def noun_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    return {
        "noun": _noun_view(
            await store.get_noun_any(context.tenant_id, str(params["id"]))
        )
    }


async def verb_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    verb_id = str(params["id"])
    verb = await store.get_verb_any(context.tenant_id, verb_id)
    if verb is None:
        raise AdapterFailure(
            "verb not found", status_code=404, reason="control_resource_not_found"
        )
    if verb_id.startswith("control."):
        raise AdapterFailure(
            "control verbs are protected",
            status_code=409,
            reason="control_resource_protected",
        )
    return {
        "verb": _verb_view(verb),
        "noun": _noun_view(
            await store.get_noun_any(context.tenant_id, verb.noun_id)
        ),
        "binding": _binding_view(
            await store.get_binding(context.tenant_id, verb_id)
        ),
    }


async def verb_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    verb_id = str(params["id"])
    current = await store.get_verb_any(context.tenant_id, verb_id)
    noun_id = str(params["noun_id"])
    noun = await store.get_noun_any(context.tenant_id, noun_id)
    if noun is None:
        raise AdapterFailure(
            "noun not found", status_code=404, reason="control_resource_not_found"
        )
    if not noun.is_active and (current is None or current.noun_id != noun_id):
        raise AdapterFailure(
            "noun is archived",
            status_code=409,
            reason="authored_definition_inactive",
        )
    return {
        "verb": _verb_view(current),
        "noun": _noun_view(noun),
        "binding": _binding_view(
            await store.get_binding(context.tenant_id, verb_id)
        ),
    }


async def binding_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    verb_id = str(params["verb_id"])
    verb = await store.get_verb_any(context.tenant_id, verb_id)
    if verb is None:
        raise AdapterFailure(
            "verb not found", status_code=404, reason="control_resource_not_found"
        )
    noun = await store.get_noun_any(context.tenant_id, verb.noun_id)
    if not verb.is_active or noun is None or not noun.is_active:
        raise AdapterFailure(
            "verb or noun is archived",
            status_code=409,
            reason="authored_definition_inactive",
        )
    return {
        "verb": _verb_view(verb),
        "noun": _noun_view(noun),
        "binding": _binding_view(
            await store.get_binding(context.tenant_id, verb_id)
        ),
    }


async def capability_upsert_context(
    store: Any, params: dict[str, Any], context: InvocationContext
) -> dict[str, Any]:
    current = next(
        (
            item
            for item in await store.list_all_capabilities(context.tenant_id)
            if item.name == params["name"]
        ),
        None,
    )
    endpoint_id = str(params.get("model_endpoint") or "").strip() or None
    vision_endpoint_id = (
        str(params.get("vision_model_endpoint") or "").strip() or None
    )
    endpoint = await store.get_model_endpoint(context.tenant_id, endpoint_id) if endpoint_id else None
    vision_endpoint = (
        await store.get_model_endpoint(context.tenant_id, vision_endpoint_id)
        if vision_endpoint_id
        else None
    )
    for role, selected_id, selected in (
        ("text", endpoint_id, endpoint),
        ("vision", vision_endpoint_id, vision_endpoint),
    ):
        if selected_id and (selected is None or not selected.is_active):
            raise AdapterFailure(
                "model endpoint binding is missing or retired",
                status_code=409,
                reason="model_endpoint_binding_unavailable",
            )
        if selected_id and not selected.supports(role):
            raise AdapterFailure(
                f"{role} model endpoint does not advertise {role} modality",
                status_code=409,
                reason="model_endpoint_modality_unavailable",
            )
    if endpoint_id and not vision_endpoint_id and not endpoint.supports("vision"):
        raise AdapterFailure(
            "a single agent model must advertise both text and vision modalities",
            status_code=409,
            reason="multimodal_model_required",
        )
    return {
        "capability": (
            None
            if current is None
            else {
                "name": current.name,
                "runtime": current.runtime,
                "supported_skills": current.supported_skills,
                "max_depth": current.max_depth,
                "is_ephemeral": current.is_ephemeral,
                "cost_tier": current.cost_tier,
                "model_endpoint": current.model_endpoint,
                "vision_model_endpoint": current.vision_model_endpoint,
                "source": current.source,
                "is_active": current.is_active,
            }
        ),
        "model_endpoint": model_endpoint_view(endpoint),
    }
