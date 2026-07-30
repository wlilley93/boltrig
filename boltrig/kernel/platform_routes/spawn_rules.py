"""Read-only effective spawn-rule inventory and no-side-effect simulation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request

from boltrig.config.spawn_rules import (
    EffectiveSpawnRules,
    SpawnRuleMatchError,
    SpawnRuleValidationError,
    effective_spawn_rules,
    parse_intent_tags,
    select_spawn_rule,
    spawn_rule_conflicts,
)

from ._shared import platform_state, require_author


def _rule_view(rule: Any) -> dict[str, Any]:
    return {
        "id": rule.name,
        "priority": rule.priority,
        "intent_tags": list(rule.intent_tags),
        "capability": rule.capability,
        "skills_added": list(rule.skills),
        "max_depth": rule.max_depth,
    }


def _generation(snapshot: EffectiveSpawnRules) -> str:
    payload = [_rule_view(rule) for rule in snapshot.rules]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _load_snapshot(
    request: Request,
    kernel: Any,
    tenant_id: str,
) -> tuple[EffectiveSpawnRules | None, str | None]:
    base_rules = platform_state(request).get("spawn_rules", ())
    try:
        return (
            await effective_spawn_rules(kernel.store, tenant_id, base_rules),
            None,
        )
    except SpawnRuleValidationError:
        return None, "invalid_policy"
    except Exception:
        return None, "policy_unavailable"


def register(app, P, K) -> None:
    @app.get("/v1/spawn-rules")
    async def list_spawn_rules(request: Request, k=K, p=P) -> dict[str, Any]:
        require_author(p)
        snapshot, failure = await _load_snapshot(request, k, p.tenant_id)
        if snapshot is None:
            return {
                "policy": {
                    "state": failure,
                    "source": None,
                    "revision_id": None,
                    "generation": None,
                    "rules": [],
                    "conflicts": [],
                    "execution_input": "server_trusted_classification_only",
                }
            }
        conflicts = [
            conflict.receipt()
            for conflict in spawn_rule_conflicts(snapshot.rules)
        ]
        return {
            "policy": {
                "state": "conflicted" if conflicts else "ready",
                "source": snapshot.source,
                "revision_id": snapshot.revision_id,
                "generation": _generation(snapshot),
                "rules": [_rule_view(rule) for rule in snapshot.rules],
                "conflicts": conflicts,
                "execution_input": "server_trusted_classification_only",
            }
        }

    @app.post("/v1/spawn-rules/simulate")
    async def simulate_spawn_rule(
        request: Request,
        body: dict[str, Any],
        k=K,
        p=P,
    ) -> dict[str, Any]:
        require_author(p)
        snapshot, failure = await _load_snapshot(request, k, p.tenant_id)
        if snapshot is None:
            return {
                "status": failure,
                "input_trust": "untrusted_preview_only",
                "selection": None,
            }
        try:
            tags = parse_intent_tags(body.get("intent_tags", []))
            selected = select_spawn_rule(snapshot.rules, tags)
        except SpawnRuleValidationError:
            return {
                "status": "invalid_input",
                "input_trust": "untrusted_preview_only",
                "selection": None,
            }
        except SpawnRuleMatchError as exc:
            return {
                "status": "conflict",
                "input_trust": "untrusted_preview_only",
                "selection": None,
                "reason": str(exc),
            }
        return {
            "status": "matched" if selected is not None else "no_match",
            "input_trust": "untrusted_preview_only",
            "selection": None if selected is None else _rule_view(selected),
            "generation": _generation(snapshot),
        }


__all__ = ["register"]
