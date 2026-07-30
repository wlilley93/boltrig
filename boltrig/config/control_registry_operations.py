"""Governed authored registry mutations for the control-plane adapter."""

from __future__ import annotations

from typing import Any

from boltrig.adapters.base import Result
from boltrig.models import InvocationContext

from .control_approval import require_unchanged_approval_context
from .control_operations import (
    set_binding_record,
    upsert_noun_record,
    upsert_skill_record,
    upsert_verb_record,
)

REGISTRY_VERBS = frozenset(
    {
        "control.skill.upsert",
        "control.skill.archive",
        "control.skill.restore",
        "control.noun.define",
        "control.noun.archive",
        "control.noun.restore",
        "control.verb.define",
        "control.verb.archive",
        "control.verb.restore",
        "control.binding.set",
    }
)


async def _skill_operation(store: Any, verb: str, params: dict, tenant: str):
    if verb == "control.skill.upsert":
        skill = await upsert_skill_record(store, tenant, params)
        return Result.success(
            {"upserted": "skill", "id": skill.id, "version": skill.version}
        )
    if verb not in {"control.skill.archive", "control.skill.restore"}:
        return None
    skill = await store.set_skill_active(
        tenant, params["id"], verb.endswith(".restore")
    )
    if skill is None:
        raise LookupError("skill not found")
    return Result.success(
        {
            "id": skill.id,
            "definition_status": "active" if skill.is_active else "archived",
        }
    )


async def _noun_operation(store: Any, verb: str, params: dict, tenant: str):
    if verb == "control.noun.define":
        noun = await upsert_noun_record(store, tenant, params)
        return Result.success({"upserted": "noun", "id": noun.id})
    if verb not in {"control.noun.archive", "control.noun.restore"}:
        return None
    noun = await store.set_noun_active(
        tenant, params["id"], verb.endswith(".restore")
    )
    if noun is None:
        raise LookupError("noun not found")
    return Result.success(
        {
            "id": noun.id,
            "definition_status": "active" if noun.is_active else "archived",
        }
    )


async def _verb_operation(store: Any, verb: str, params: dict, tenant: str):
    if verb == "control.verb.define":
        defined = await upsert_verb_record(store, tenant, params)
        return Result.success(
            {
                "upserted": "verb",
                "id": defined.id,
                "consequence": defined.consequence.value,
            }
        )
    if verb not in {"control.verb.archive", "control.verb.restore"}:
        return None
    defined = await store.set_verb_active(
        tenant, params["id"], verb.endswith(".restore")
    )
    if defined is None:
        raise LookupError("verb not found")
    return Result.success(
        {
            "id": defined.id,
            "definition_status": "active" if defined.is_active else "archived",
        }
    )


async def _binding_operation(store: Any, verb: str, params: dict, tenant: str):
    if verb != "control.binding.set":
        return None
    binding = await set_binding_record(
        store, tenant, params["verb_id"], params
    )
    return Result.success(
        {
            "upserted": "binding",
            "verb": binding.verb_id,
            "target": binding.target_ref,
        }
    )


async def execute_registry_operation(
    store: Any,
    loader: Any,
    verb: str,
    params: dict[str, Any],
    context: InvocationContext,
) -> Result | None:
    if verb not in REGISTRY_VERBS:
        return None
    await require_unchanged_approval_context(
        store, loader, verb, params, context
    )
    handlers = (
        _skill_operation,
        _noun_operation,
        _verb_operation,
        _binding_operation,
    )
    for handler in handlers:
        result = await handler(store, verb, params, context.tenant_id)
        if result is not None:
            return result
    raise AssertionError(f"unhandled registry verb: {verb}")
