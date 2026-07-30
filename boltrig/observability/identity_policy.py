"""Redacted projection of effective process-start authentication trust."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def compose_identity_policy(manifest: Any, settings: Any) -> dict[str, Any]:
    identity = getattr(manifest, "identity", None)
    manifest_values = (
        str(getattr(identity, "issuer", "") or "").strip(),
        str(getattr(identity, "audience", "") or "").strip(),
        str(getattr(identity, "jwks_uri", "") or "").strip(),
    )
    process_values = (
        str(getattr(settings, "oidc_issuer", "") or "").strip(),
        str(getattr(settings, "oidc_audience", "") or "").strip(),
        str(getattr(settings, "oidc_jwks_uri", "") or "").strip(),
    )
    manifest_configured = all(manifest_values)
    process_configured = all(process_values)
    manifest_state = (
        "complete"
        if manifest_configured
        else "partial"
        if any(manifest_values)
        else "absent"
    )
    process_state = (
        "complete"
        if process_configured
        else "partial"
        if any(process_values)
        else "absent"
    )
    if bool(getattr(settings, "session_auth_configured", False)):
        mode = "first_party_session"
    elif bool(getattr(settings, "cf_access_configured", False)):
        mode = "cloudflare_access"
    elif manifest_configured or process_configured:
        mode = "oidc"
    elif bool(getattr(settings, "dev_auth", False)):
        mode = "development_header_trust"
    else:
        mode = "deny_all"
    if mode == "oidc":
        serving_state = (
            "active_manifest_and_process_match"
            if manifest_configured and process_configured
            else "active_manifest"
            if manifest_configured
            else "active_process"
        )
    elif any(manifest_values):
        serving_state = "inactive_selected_other_auth_mode"
    else:
        serving_state = "not_configured"
    generation_payload = {
        "mode": mode,
        "manifest": manifest_values,
        "process": process_values,
    }
    return {
        "status": "available",
        "mode": mode,
        "oidc": {
            "manifest_trio_configured": manifest_configured,
            "process_trio_configured": process_configured,
            "manifest_trio_state": manifest_state,
            "process_trio_state": process_state,
            "serving_state": serving_state,
            "drift_policy": "exact_match_or_boot_refused",
        },
        "generation": hashlib.sha256(
            json.dumps(
                generation_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "changes_apply_at": "process_restart",
        "sensitive_values_redacted": True,
    }


_MODES = {
    "first_party_session",
    "cloudflare_access",
    "oidc",
    "development_header_trust",
    "deny_all",
}
_SERVING_STATES = {
    "active_manifest_and_process_match",
    "active_manifest",
    "active_process",
    "inactive_selected_other_auth_mode",
    "not_configured",
}


def identity_policy_projection(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {
            "status": "unavailable",
            "mode": "deny_all",
            "oidc": {
                "manifest_trio_configured": False,
                "process_trio_configured": False,
                "manifest_trio_state": "absent",
                "process_trio_state": "absent",
                "serving_state": "not_configured",
                "drift_policy": "exact_match_or_boot_refused",
            },
            "generation": None,
            "changes_apply_at": "process_restart",
            "sensitive_values_redacted": True,
        }
    oidc = raw.get("oidc")
    if not isinstance(oidc, Mapping):
        oidc = {}
    mode = raw.get("mode")
    serving = oidc.get("serving_state")
    generation = raw.get("generation")
    return {
        "status": "available" if raw.get("status") == "available" else "unavailable",
        "mode": mode if mode in _MODES else "deny_all",
        "oidc": {
            "manifest_trio_configured": (
                oidc.get("manifest_trio_configured") is True
            ),
            "process_trio_configured": (
                oidc.get("process_trio_configured") is True
            ),
            "manifest_trio_state": (
                oidc.get("manifest_trio_state")
                if oidc.get("manifest_trio_state")
                in {"absent", "partial", "complete"}
                else "absent"
            ),
            "process_trio_state": (
                oidc.get("process_trio_state")
                if oidc.get("process_trio_state")
                in {"absent", "partial", "complete"}
                else "absent"
            ),
            "serving_state": (
                serving if serving in _SERVING_STATES else "not_configured"
            ),
            "drift_policy": "exact_match_or_boot_refused",
        },
        "generation": (
            generation
            if isinstance(generation, str) and len(generation) == 64
            else None
        ),
        "changes_apply_at": "process_restart",
        "sensitive_values_redacted": True,
    }


__all__ = ["compose_identity_policy", "identity_policy_projection"]
