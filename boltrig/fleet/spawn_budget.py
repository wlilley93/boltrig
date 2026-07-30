"""Shared deterministic budget helpers for agent spawning and bound invocation."""

from __future__ import annotations

from typing import Any

from boltrig.kernel.cost import price_micros


def budget_scope_ids(tenant_id: str, department: Any | None) -> list[str]:
    """Return the persisted tenant and optional department budget scope IDs."""
    return [tenant_id, *([str(department)] if department else [])]


def estimate(task: str, prompt: str, skills: list[str], cost_tier: str) -> tuple[int, int]:
    """Deterministic pre-run token/cost estimate for budget reservation."""
    chars = len(task) + len(prompt) + sum(len(skill) for skill in skills)
    tokens = max(16, chars // 4)
    return tokens, price_micros(tokens, cost_tier)
