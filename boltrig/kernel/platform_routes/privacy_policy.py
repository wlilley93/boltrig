"""Caller-visible effective privacy-policy coverage."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import Request

from ._shared import platform_state


def register(app, P, K) -> None:
    @app.get("/v1/privacy/policy")
    async def get_privacy_policy(request: Request, p=P) -> dict[str, Any]:
        policy = platform_state(request).get("privacy_policy")
        if policy is None:
            return {
                "policy": {
                    "state": "unconfigured",
                    "source": "no_process_manifest",
                    "generation": None,
                    "retention": {
                        "days": None,
                        "serving_state": "not_configured",
                        "coverage": [],
                    },
                    "redaction": {
                        "configured": False,
                        "fields": [],
                        "serving_state": "inactive_no_consumer",
                    },
                    "residency": {
                        "region": None,
                        "serving_state": "inactive_no_consumer",
                    },
                    "compliance_export": "account_summary_only",
                }
            }
        safe = {
            "retention_days": policy.retention_days,
            "pii_redaction": policy.pii_redaction,
            "data_residency": policy.data_residency,
            "redact_fields": sorted(policy.redact_fields),
        }
        generation = hashlib.sha256(
            json.dumps(safe, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "policy": {
                "state": "partial",
                "source": "process_start_manifest",
                "generation": generation,
                "retention": {
                    "days": policy.retention_days,
                    "serving_state": (
                        "closed_conversations_only"
                        if policy.retention_days is not None
                        else "not_configured"
                    ),
                    "coverage": ["closed_conversation_messages"],
                },
                "redaction": {
                    "configured": policy.pii_redaction,
                    "fields": safe["redact_fields"],
                    "serving_state": "inactive_no_consumer",
                },
                "residency": {
                    "region": policy.data_residency,
                    "serving_state": "inactive_no_consumer",
                },
                "compliance_export": "account_summary_only",
            }
        }


__all__ = ["register"]
