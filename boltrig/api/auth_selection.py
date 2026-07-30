"""Authentication resolver selection from immutable boot policy."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

log = logging.getLogger("boltrig.bootstrap")


def _oidc_trio(source: Any) -> tuple[str, str, str]:
    return (
        str(getattr(source, "issuer", "") or "").strip(),
        str(getattr(source, "audience", "") or "").strip(),
        str(getattr(source, "jwks_uri", "") or "").strip(),
    )


def _session_resolver(settings: Any, default_tenant: str):
    from boltrig.identity import build_session_resolver

    tenant = settings.session_tenant or default_tenant
    log.info("first-party session auth enabled (tenant %s)", tenant)
    return build_session_resolver(tenant)


def _cf_access_resolver(settings: Any, default_tenant: str):
    from boltrig.identity import OidcVerifier, build_cf_access_resolver

    try:
        role_map = json.loads(settings.cf_access_role_map) if settings.cf_access_role_map else {}
    except (ValueError, TypeError):
        log.error("CF_ACCESS_ROLE_MAP is not valid JSON; treating as empty (deny-by-default)")
        role_map = {}
    team = settings.cf_access_team_domain
    verifier = OidcVerifier(
        issuer=team,
        audience=settings.cf_access_aud,
        jwks_uri=f"{team}/cdn-cgi/access/certs",
    )
    log.info(
        "Cloudflare Access auth enabled (team %s, %d mapped emails)",
        team,
        len(role_map),
    )
    return build_cf_access_resolver(
        verifier=verifier,
        tenant_id=settings.cf_access_tenant or default_tenant,
        role_map=role_map,
        default_role=settings.cf_access_default_role,
    )


def _generic_oidc_resolver(
    settings: Any,
    manifest: Any,
    default_tenant: str,
):
    from boltrig.identity import OidcVerifier, build_principal_resolver

    manifest_oidc = _oidc_trio(getattr(manifest, "identity", None))
    environment_oidc = (
        str(settings.oidc_issuer or "").strip(),
        str(settings.oidc_audience or "").strip(),
        str(settings.oidc_jwks_uri or "").strip(),
    )
    if any(manifest_oidc) and not all(manifest_oidc):
        raise RuntimeError(
            "manifest identity OIDC trust is partial; issuer, audience and "
            "jwks_uri must be configured together"
        )
    if all(manifest_oidc) and all(environment_oidc) and manifest_oidc != environment_oidc:
        raise RuntimeError("manifest identity OIDC trust differs from process OIDC trust")
    selected = manifest_oidc if all(manifest_oidc) else environment_oidc
    if not all(selected):
        return None
    mappings = list(manifest.role_mappings) if manifest is not None else []
    tenant = manifest.tenant_id if manifest is not None else default_tenant
    issuer, audience, jwks_uri = selected
    log.info(
        "OIDC auth enabled from %s trust policy (issuer %s)",
        "manifest" if all(manifest_oidc) else "process",
        issuer,
    )
    return build_principal_resolver(
        verifier=OidcVerifier(issuer, audience, jwks_uri),
        mappings=mappings,
        tenant_id=tenant,
    )


def select_auth_resolver(
    settings: Any,
    manifest: Any,
    *,
    default_tenant: str,
    refuse_dev_auth_in_prod: Callable[[], None],
    deny_all_resolver: Callable[[], Any],
):
    """Select one fail-closed authentication posture."""

    if settings.session_auth_configured:
        return _session_resolver(settings, default_tenant)
    if settings.cf_access_configured:
        return _cf_access_resolver(settings, default_tenant)
    resolver = _generic_oidc_resolver(settings, manifest, default_tenant)
    if resolver is not None:
        return resolver
    if settings.dev_auth:
        refuse_dev_auth_in_prod()
        log.warning(
            "BOLTRIG_DEV_AUTH=1: header-trusting dev auth is active. NOT for production (SEC-01)."
        )
        return None
    log.warning(
        "no OIDC_* config and BOLTRIG_DEV_AUTH unset: refusing all requests "
        "(fail-closed). Set OIDC_ISSUER/OIDC_AUDIENCE/OIDC_JWKS_URI for "
        "production, or BOLTRIG_DEV_AUTH=1 for dev."
    )
    return deny_all_resolver()


__all__ = ["select_auth_resolver"]
