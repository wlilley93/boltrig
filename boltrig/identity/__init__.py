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
from .rbac import DEFAULT_ROLE, ROLE_PRECEDENCE, grants_for_scope, resolve_role

__all__ = [
    "OidcVerifier",
    "SamlVerifier",
    "Verifier",
    "build_cf_access_resolver",
    "build_principal_resolver",
    "dev_principal_resolver",
    "OnBehalfOf",
    "TokenExchanger",
    "SERVICE_PRINCIPAL",
    "DELEGATED",
    "resolve_role",
    "grants_for_scope",
    "ROLE_PRECEDENCE",
    "DEFAULT_ROLE",
]
