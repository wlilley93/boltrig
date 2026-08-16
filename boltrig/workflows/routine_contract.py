"""Closed v1 contract for conversational routines.

A routine is deliberately smaller than the legacy workflow graph: one trigger
supplies inputs to one governed agent turn and the resulting conversation is the
run record people follow. Graph authoring is not part of the v1 product.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROUTINE_KEY = "_boltrig_routine"
ROUTINE_VERSION = 1
ROUTINE_COMPANIONS = frozenset({"familiar", "jarvis"})
_ROUTINE_FIELDS = frozenset({"version", "name", "goal", "companion_id", "notify"})
_NOTIFY_FIELDS = frozenset({"completion"})


@dataclass(frozen=True)
class RoutineSpec:
    name: str
    goal: str
    companion_id: str
    notify_completion: bool


def routine_spec(definition: dict[str, Any]) -> RoutineSpec | None:
    raw = definition.get(ROUTINE_KEY)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("routine must be an object")
    unknown = set(raw) - _ROUTINE_FIELDS
    if unknown:
        raise ValueError(f"routine has unknown field: {sorted(unknown)[0]}")
    if raw.get("version") != ROUTINE_VERSION:
        raise ValueError("routine version must be 1")
    name = _bounded_text(raw.get("name"), "routine name", 120)
    goal = _bounded_text(raw.get("goal"), "routine goal", 4_000)
    companion_id = str(raw.get("companion_id") or "").strip().lower()
    if companion_id not in ROUTINE_COMPANIONS:
        raise ValueError("routine companion must be familiar or jarvis")
    notify = raw.get("notify", {})
    if not isinstance(notify, dict):
        raise ValueError("routine notify must be an object")
    unknown_notify = set(notify) - _NOTIFY_FIELDS
    if unknown_notify:
        raise ValueError(
            f"routine notify has unknown field: {sorted(unknown_notify)[0]}"
        )
    completion = notify.get("completion", True)
    if type(completion) is not bool:
        raise ValueError("routine notification choices must be boolean")
    steps = definition.get("steps", [])
    if not isinstance(steps, list) or steps:
        raise ValueError("v1 conversational routines cannot contain graph steps")
    return RoutineSpec(name, goal, companion_id, completion)


def require_valid_routine_contract(definition: dict[str, Any]) -> None:
    routine_spec(definition)


def _bounded_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} must be between 1 and {maximum} characters")
    return text


__all__ = [
    "ROUTINE_COMPANIONS",
    "ROUTINE_KEY",
    "ROUTINE_VERSION",
    "RoutineSpec",
    "require_valid_routine_contract",
    "routine_spec",
]
