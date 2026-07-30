"""Non-secret author projections for authored definitions."""

from __future__ import annotations


def skill_view(skill, *, detail: bool = False) -> dict:
    payload = {
        "id": skill.id,
        "version": skill.version,
        "extends": skill.extends,
        "tool_grants": skill.tool_grants,
        "locale": skill.locale,
        "is_active": skill.is_active,
        "status": "active" if skill.is_active else "archived",
    }
    if detail:
        payload.update(
            {
                "prompt_fragment": skill.prompt_fragment,
                "context_requirements": skill.context_requirements,
                "description": skill.description,
            }
        )
    return payload


def noun_view(noun) -> dict:
    return {
        "id": noun.id,
        "description": noun.description,
        "schema": noun.schema,
        "is_active": noun.is_active,
        "status": "active" if noun.is_active else "archived",
    }


def _rate_limit_view(rate_limit) -> dict | None:
    if rate_limit is None:
        return None
    return {
        "per": rate_limit.per,
        "max": rate_limit.max,
        "scope": rate_limit.scope,
    }


def binding_view(binding) -> dict | None:
    if binding is None:
        return None
    return {
        "target_type": binding.target_type.value,
        "target_ref": binding.target_ref,
        "rate_limit": _rate_limit_view(binding.rate_limit),
    }


async def verb_view(store, tenant_id: str, verb) -> dict:
    binding = await store.get_binding(tenant_id, verb.id)
    noun = await store.get_noun_any(tenant_id, verb.noun_id)
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
        "status": "active" if verb.is_active else "archived",
        "noun_status": (
            "active" if noun is not None and noun.is_active else "archived"
        ),
        "binding": binding_view(binding),
    }
