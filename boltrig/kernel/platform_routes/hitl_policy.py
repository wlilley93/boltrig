"""Redacted process-start approval-policy projection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request

from ._shared import platform_state, require_author


def register(app, P, K) -> None:
    @app.get("/v1/hitl/policy")
    async def get_hitl_policy(request: Request, p=P) -> dict[str, Any]:
        require_author(p)
        policy = platform_state(request).get("hitl_policy")
        if policy is None:
            return {
                "policy": {
                    "state": "unconfigured",
                    "source": "no_process_manifest",
                    "generation": None,
                    "blocking_verbs": [],
                    "approval_timeout_seconds": None,
                    "routing": {
                        "primary_channel": None,
                        "notify_via": [],
                        "escalation_chain": [],
                        "serving_state": "inactive_no_consumer",
                    },
                    "changes_apply_at": "process_restart",
                }
            }
        safe = {
            "blocking_verbs": sorted(policy.blocking_verbs),
            "approval_timeout_seconds": policy.approval_timeout_seconds,
            "routing": {
                "primary_channel": policy.primary_channel,
                "notify_via": list(policy.notify_via),
                "escalation_chain": list(policy.escalation_chain),
            },
        }
        generation = hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "policy": {
                "state": "configured",
                "source": "process_start_manifest",
                "generation": generation,
                "blocking_verbs": safe["blocking_verbs"],
                "approval_timeout_seconds": safe["approval_timeout_seconds"],
                "routing": {
                    **safe["routing"],
                    "serving_state": "inactive_no_consumer",
                },
                "changes_apply_at": "process_restart",
            }
        }


__all__ = ["register"]
