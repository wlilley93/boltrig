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

from boltrig.models import EMPTY_GRANTS, GrantSet, RoleMapping

# Most-privileged first. A caller in several groups gets the highest role they
# are mapped to. Unknown roles rank below every named role (least privilege).
# superadmin / admin / member are the console's product tiers (SEC-01): superadmin
# is the owner, admin is a full operator+configurator, member operates but cannot
# author or administer. They sit above the finer IdP-group roles.
ROLE_PRECEDENCE: tuple[str, ...] = (
    "superadmin",
    "admin",
    "org-admin",
    "department-head",
    "manager",
    "engineer",
    "member",
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
    return scope is not None and scope.get("all") is True


def resolve_role(groups: list[str], mappings: list[RoleMapping]) -> tuple[str, dict[str, Any]]:
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


# Roles permitted to author (studios) and administer (admin console) (C3, SEC-32).
# superadmin + admin author/administer; member deliberately does NOT (it operates
# only - the console's authoring studios and admin console are hidden from it).
AUTHOR_ROLES: frozenset[str] = frozenset(
    {"superadmin", "admin", "org-admin", "department-head", "manager", "lead", "integrator"}
)


# --- workspace-role grant ceilings ([2026] VJS-COUNTY 8, D11) ----------------
#
# A caller who is operating INSIDE an active workspace has their org/user grants
# NARROWED by the workspace role they hold there: effective = (org grants) ∩ (the
# workspace-role ceiling). This composes with [2026] VJS-COUNTY 5 (authority is
# only ever intersected DOWN, never widened): a workspace membership can only take
# authority away, never add it. A caller with NO active workspace keeps their org
# grants unchanged (that path never reaches here) - backward-compat is pinned.
#
# The ceilings are expressed in the SAME grant vocabulary as the role/scope
# mapping above (allow/deny verb patterns, terminal-wildcard K-9). The one axis the
# pattern grammar expresses cleanly is the CONFIGURE / ADMINISTER namespace: every
# registry / studio / admin-console mutation lives under the ``control.*`` verb
# namespace, so "operate" tiers deny it and "configure" tiers keep it. Workspace
# self-administration (its own membership / settings) is the finer ``control.workspace.*``
# slice, owner-only.
#
#   owner  -> broad: everything the org already grants (administers the workspace).
#   admin  -> operate + configure: all resource + registry verbs, but NOT workspace
#             self-administration (``control.workspace.*`` is owner-only).
#   member -> operate only: resource verbs, but NO configure/administer (``control.*``).
#   agent  -> the agent ceiling: a non-human runtime seat operates but never
#             authors/administers (same operate ceiling as member; ``control.*`` denied).
#   viewer -> read-only: NO write verb at all (handled specially below - "read-only"
#             is not a namespace the terminal-wildcard grammar can express as one
#             pattern, so it is derived per granted verb from its action suffix).
WORKSPACE_ROLE_CEILINGS: dict[str, GrantSet] = {
    "owner": GrantSet.of(allow=["*"]),
    "admin": GrantSet.of(allow=["*"], deny=["control.workspace.*"]),
    "member": GrantSet.of(allow=["*"], deny=["control.*"]),
    "agent": GrantSet.of(allow=["*"], deny=["control.*"]),
}

# Action suffixes that only READ (never mutate). A viewer keeps a granted verb only
# when its action is one of these. A wildcard grant (``*`` or ``noun.*``) spans
# writes, so a viewer cannot keep it: it collapses (fail-closed, never widen).
READ_ACTIONS: frozenset[str] = frozenset(
    {
        "read",
        "list",
        "get",
        "search",
        "describe",
        "view",
        "show",
        "recall",
        "fetch",
        "peek",
        "export",
        "download",
        "stream",
        "query",
    }
)


def workspace_role_ceiling(role: str) -> GrantSet | None:
    """The verb-grant ceiling for a workspace role (D11), or ``None`` when the role
    has no namespace ceiling (``viewer``, handled by :func:`narrow_grants_to_workspace`,
    and any unknown role, which fails closed)."""
    return WORKSPACE_ROLE_CEILINGS.get(role)


def _is_read_only_pattern(pattern: str) -> bool:
    """Whether a grant pattern authorises ONLY reads. A terminal wildcard (``*`` or
    ``<noun>.*``) spans writes and so is not read-only; a concrete ``<noun>.<action>``
    is read-only iff its action is in :data:`READ_ACTIONS`."""
    if pattern == "*" or pattern.endswith(".*"):
        return False
    _, _, action = pattern.rpartition(".")
    return action in READ_ACTIONS


def narrow_grants_to_workspace(base: GrantSet, workspace_role: str) -> GrantSet:
    """Narrow ``base`` (the caller's org/user grants) by a workspace role's ceiling
    ([2026] VJS-COUNTY 8, D11; composes with COUNTY 5 - intersect DOWN, never widen).

    The result is always a SUBSET of ``base``: this can only take authority away.
      * ``viewer`` -> read-only: keep only the base allow-patterns that authorise a
        concrete read verb (wildcards collapse, fail-closed); base denies carry
        through (deny-dominant, K-5).
      * ``owner`` / ``admin`` / ``member`` / ``agent`` -> intersect with the role's
        ``control.*`` namespace ceiling (``GrantSet.intersect`` keeps only base
        allows the ceiling permits and unions the denies).
      * any unknown role -> ``EMPTY_GRANTS`` (fail-closed - never widen).
    """
    if workspace_role == "viewer":
        allow = tuple(p for p in base.allow if _is_read_only_pattern(p))
        return GrantSet(allow=allow, deny=base.deny)
    ceiling = WORKSPACE_ROLE_CEILINGS.get(workspace_role)
    if ceiling is None:
        return EMPTY_GRANTS  # unknown workspace role -> no authority (fail-closed)
    return base.intersect(ceiling)


def can_author(role: str) -> bool:
    """Whether a role may use the authoring studios / admin console (SEC-32)."""
    return role in AUTHOR_ROLES


def memory_owner_scopes(user_id: str, role: str, scope: dict[str, Any] | None) -> list[str]:
    """The memory owner-scopes a caller may read (SEC-31): their own user, the org
    scope, and any department in their visibility scope. Excludes other users'
    and other departments' memory, so cross-scope reads are denied."""
    scopes = [f"user:{user_id}", "org"]
    for dept in departments_for(role, scope) or []:
        scopes.append(f"department:{dept}")
    return scopes


def departments_for(role: str, scope: dict[str, Any] | None) -> list[str] | None:
    """The caller's row-level department scope for work listing (US-IAM-02).

    Returns ``None`` for unrestricted access (org-admin, or ``{all: true}``) and
    otherwise the list of departments the caller may see (possibly empty, which
    is fail-closed: an engineer with no department sees nothing).
    """
    if role == "org-admin" or _scope_is_all(scope):
        return None
    return list((scope or {}).get("departments", []) or [])
