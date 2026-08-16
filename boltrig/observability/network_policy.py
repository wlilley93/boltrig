"""Redacted projection of effective network-policy coverage."""

from __future__ import annotations

from typing import Any


_SEPARATE_SURFACES: tuple[dict[str, Any], ...] = (
    {
        "surface": "browser",
        "status": "separate_policy",
        "manifest_network_policy": "not_applied",
        "controls": (
            "browser_specific_domain_allowlist",
            "shared_ssrf_preflight",
        ),
        "limitation": "browser_process_performs_the_network_request",
    },
    {
        "surface": "external_mcp",
        "status": "shared_policy",
        "manifest_network_policy": "applied",
        "controls": (
            "governed_server_registration",
            "shared_ssrf_and_dns_pinning",
            "manifest_airgap_and_domain_lists",
            "manifest_proxy_and_ca_rules",
            "reviewed_internal_server_waiver",
        ),
        "limitation": "proxy_mode_delegates_resolution_to_the_proxy",
    },
    {
        "surface": "http_adapters",
        "status": "shared_policy",
        "manifest_network_policy": "applied",
        "controls": (
            "adapter_specific_shared_ssrf_or_dns_pinning",
            "manifest_airgap_and_domain_lists",
            "manifest_proxy_and_ca_rules",
        ),
        "limitation": "coverage_varies_by_adapter_family",
    },
    {
        "surface": "model_providers_and_embeddings",
        "status": "provider_transport_only",
        "manifest_network_policy": "not_applied",
        "controls": ("configured_provider_endpoints",),
        "limitation": "no_universal_manifest_egress_enforcement",
    },
)


def effective_network_policy(kernel: Any, tenant_id: str) -> dict[str, Any]:
    """Project only policy facts observable from the live web adapter.

    No proxy URL, CA path/content, domain value or provider endpoint is returned.
    The other rows deliberately describe coverage boundaries instead of inferring
    that one adapter's policy is a process- or deployment-wide firewall.
    """
    try:
        adapter = kernel.loader.peek(tenant_id, "web")
        posture = getattr(adapter, "network_policy_posture", None)
        web_fetch = posture() if callable(posture) else None
    except Exception:
        web_fetch = None

    return {
        "status": "available" if isinstance(web_fetch, dict) else "unavailable",
        "policy_source": "live_adapter_process_start_snapshot",
        "changes_require_restart": True,
        "universal_egress_control": False,
        "sensitive_values_redacted": True,
        "web_fetch": web_fetch,
        "coverage": [
            {**item, "controls": list(item["controls"])}
            for item in _SEPARATE_SURFACES
        ],
    }


__all__ = ["effective_network_policy"]
