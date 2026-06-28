"""IdP-group -> platform-role + visibility-scope mapping (US-IAM-02, SEC-07).

The IdP is the source of truth for who a caller is and which groups they hold.
This module turns those groups into (a) a platform role and (b) a visibility
scope, and turns a scope into a ``GrantSet`` ceiling over verbs. The scope is
what stops an engineer from seeing another department's queue: it drives the
GrantSet ceiling, and least privilege is the default (fail-closed: no match ->
no authority).
"""

from __future__ import annotations

from typing import Any

from nankle.models import EMPTY_GRANTS, GrantSet, RoleMapping

# Most-privileged first. A caller in several groups gets the highest role they
# are mapped to. Unknown roles rank below every named role (least privilege).
ROLE_PRECEDENCE: tuple[str, ...] = (
    "org-admin",
    "department-head",
    "manager",
    "engineer",
    "agent",
    "viewer",
)

# Returned when no IdP group matches any mapping. Fail-closed: empty scope ->
# empty GrantSet, so an unmapped caller can do nothing (K-13).
DEFAULT_ROLE = "none"


def _role_rank(role: str) -> int:
    """Rank a role for precedence; unknown roles sort last (least privilege)."""
    try:
        return ROLE_PRECEDENCE.index(role)
    except ValueError:
        return len(ROLE_PRECEDENCE)


def _scope_is_all(scope: dict[str, Any] | None) -> bool:
    """Whether a scope grants org-wide visibility (``{all: true}``)."""
    return bool(scope) and scope.get("all") is True


def resolve_role(
    groups: list[str], mappings: list[RoleMapping]
) -> tuple[str, dict[str, Any]]:
    """Map a caller's IdP groups to (platform_role, merged_scope) (US-IAM-02).

    The role is the highest-privilege role among the matched mappings. The scope
    is the union of the matched mappings' scopes (departments / nouns / verbs).
    Any ``{all: true}`` (or an org-admin mapping) collapses the merged scope to
    ``{all: true}``. No match returns ``(DEFAULT_ROLE, {})`` (fail-closed).
    """
    held = set(groups)
    matched = [m for m in mappings if m.idp_group in held]
    if not matched:
        return (DEFAULT_ROLE, {})

    role = min((m.role for m in matched), key=_role_rank)

    if role == "org-admin" or any(_scope_is_all(m.scope) for m in matched):
        return (role, {"all": True})

    departments: set[str] = set()
    nouns: set[str] = set()
    verbs: set[str] = set()
    deny: set[str] = set()
    for m in matched:
        s = m.scope or {}
        departments.update(s.get("departments", []) or [])
        nouns.update(s.get("nouns", []) or [])
        verbs.update(s.get("verbs", []) or [])
        deny.update(s.get("deny", []) or [])

    merged: dict[str, Any] = {}
    if departments:
        merged["departments"] = sorted(departments)
    if nouns:
        merged["nouns"] = sorted(nouns)
    if verbs:
        merged["verbs"] = sorted(verbs)
    if deny:
        merged["deny"] = sorted(deny)
    return (role, merged)


def grants_for_scope(scope: dict[str, Any] | None) -> GrantSet:
    """Turn a visibility scope into a verb ``GrantSet`` ceiling (US-IAM-02/04).

    Mapping:
      * ``{all: true}`` -> allow ``["*"]`` (the tenant-wide grant; org-admin).
      * otherwise -> the union of the listed ``verbs`` patterns and one
        ``<noun>.*`` pattern per listed ``nouns`` entry, with any ``deny`` list
        carried through (deny-dominant, K-5).
      * empty / missing -> ``EMPTY_GRANTS`` (fail-closed, K-13).

    Departments are visibility metadata, not verb authority, so they do not widen
    the GrantSet here; row-level department isolation is enforced separately.
    """
    if not scope:
        return EMPTY_GRANTS
    if scope.get("all") is True:
        return GrantSet.of(["*"])

    allow: list[str] = []
    seen: set[str] = set()

    def _add(pattern: str) -> None:
        if pattern and pattern not in seen:
            seen.add(pattern)
            allow.append(pattern)

    for verb in scope.get("verbs", []) or []:
        _add(verb)
    for noun in scope.get("nouns", []) or []:
        _add(noun if noun.endswith(".*") else f"{noun}.*")

    deny = [d for d in (scope.get("deny", []) or [])]
    return GrantSet.of(allow=allow, deny=deny)


def departments_for(role: str, scope: dict[str, Any] | None) -> list[str] | None:
    """The caller's row-level department scope for work listing (US-IAM-02).

    Returns ``None`` for unrestricted access (org-admin, or ``{all: true}``) and
    otherwise the list of departments the caller may see (possibly empty, which
    is fail-closed: an engineer with no department sees nothing).
    """
    if role == "org-admin" or _scope_is_all(scope):
        return None
    return list((scope or {}).get("departments", []) or [])
