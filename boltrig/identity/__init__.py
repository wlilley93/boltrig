"""Identity and SSO: token verification, RBAC, and delegation (US-IAM-01..05).

Identity is authenticated-by-construction (K-3): the kernel never trusts the
request body for who the caller is. A verifier turns a bearer into claims, RBAC
turns claims into a role + GrantSet ceiling, and delegation decides whether a
verb acts as the platform or as the user.
"""

from __future__ import annotations

from .auth import (
    OidcVerifier,
    SamlVerifier,
    Verifier,
    build_cf_access_resolver,
    build_principal_resolver,
    dev_principal_resolver,
)
from .delegation import DELEGATED, SERVICE_PRINCIPAL, OnBehalfOf, TokenExchanger
from .invites import generate_invite_token, hash_invite_token
from .passwords import (
    hash_password,
    validate_password_strength,
    verify_dummy,
    verify_password,
)
from .rbac import DEFAULT_ROLE, ROLE_PRECEDENCE, grants_for_scope, resolve_role
from .sessions import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    build_session_resolver,
    new_session,
    pick_default_org,
    pick_default_workspace,
    resolve_active_org,
    resolve_active_workspace,
    rotate_session,
)
from .tenancy import default_org_for, default_org_slug, ensure_default_org
from .totp import (
    generate_challenge_token,
    generate_recovery_codes,
    generate_totp_secret,
    hash_challenge_token,
    hash_recovery_code,
    normalize_recovery_code,
    totp_provisioning_uri,
    verify_totp,
)
from .ai_keys import (
    AiKeyResolution,
    load_ai_key_material,
    resolve_ai_key,
)

__all__ = [
    "OidcVerifier",
    "SamlVerifier",
    "Verifier",
    "build_cf_access_resolver",
    "build_principal_resolver",
    "build_session_resolver",
    "dev_principal_resolver",
    "OnBehalfOf",
    "TokenExchanger",
    "SERVICE_PRINCIPAL",
    "DELEGATED",
    "resolve_role",
    "grants_for_scope",
    "ROLE_PRECEDENCE",
    "DEFAULT_ROLE",
    # First-party invite-only login ([2026] VJS-COUNTY 7).
    "hash_password",
    "verify_password",
    "verify_dummy",
    "validate_password_strength",
    "generate_invite_token",
    "hash_invite_token",
    "new_session",
    "rotate_session",
    "pick_default_org",
    "pick_default_workspace",
    "resolve_active_org",
    "resolve_active_workspace",
    "SESSION_COOKIE",
    "CSRF_COOKIE",
    "CSRF_HEADER",
    # Org -> workspace tenancy ([2026] VJS-COUNTY 8).
    "default_org_for",
    "default_org_slug",
    "ensure_default_org",
    # Per-org/workspace/user AI keys ([2026] VJS-COUNTY 8, D5).
    "AiKeyResolution",
    "resolve_ai_key",
    "load_ai_key_material",
    # TOTP two-factor ([2026] VJS-COUNTY 10).
    "generate_totp_secret",
    "totp_provisioning_uri",
    "verify_totp",
    "generate_recovery_codes",
    "hash_recovery_code",
    "normalize_recovery_code",
    "generate_challenge_token",
    "hash_challenge_token",
]
