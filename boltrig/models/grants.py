"""The grant primitive - least-privilege authority over verbs (P8, SEC-07).

A caller (an ephemeral child) carries a ``GrantSet``: the union of its loaded
skills' ``tool_grants``, intersected with the tenant's permissions
(US-IAM-04). The kernel checks every ``/v1/invoke`` against it.

Doctrine baked in:
  * Deny-dominance (K-5): an active deny beats every allow; checked first.
  * Fail-closed (K-13): unmatched / empty / unknown -> deny.
  * Terminal wildcard only (K-9): ``jira.*`` covers ``jira.read`` but NOT
    ``jirax.read``; a prefix without a trailing ``.*`` does not match by prefix.

Grant tokens are verb ids (``ticket.create``) or terminal-wildcard verb
patterns (``ticket.*``). The lone token ``*`` is the tenant-wide grant and is
intended only for org-admin scope - never minted onto an ephemeral.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from .base import VerbId

# The safe identifier charset for verb ids / grant tokens (UPLOAD-05 / AZ-02). A
# real id is ASCII alphanumerics plus these structural chars; anything else (a
# Unicode homoglyph/confusable, a control char, a zero-width joiner) is NOT a safe
# identifier and so can never match a grant.
_SAFE_ID_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/@*")
MAX_CONCRETE_VERBS = 256
MAX_VERB_ID_BYTES = 256


def normalize_identifier(value: str) -> str:
    """NFKC-normalise an id/grant token so confusable/compatibility forms collapse
    to one canonical form before any comparison (UPLOAD-05)."""
    return unicodedata.normalize("NFKC", value or "")


def is_safe_identifier(value: str) -> bool:
    """True iff ``value`` is, after NFKC, only the safe identifier charset. A
    homoglyph (e.g. Cyrillic 'а') or control/zero-width char makes it unsafe."""
    norm = normalize_identifier(value)
    return bool(norm) and all(ch in _SAFE_ID_CHARS for ch in norm)


def canonical_concrete_verbs(values: tuple[VerbId, ...]) -> tuple[VerbId, ...]:
    """Validate and canonicalize a bounded immutable concrete-verb snapshot."""

    if type(values) is not tuple:
        raise TypeError("permitted verbs must be an immutable tuple")
    if len(values) > MAX_CONCRETE_VERBS:
        raise ValueError(f"authority snapshots permit at most {MAX_CONCRETE_VERBS} verbs")
    canonical: set[VerbId] = set()
    for value in values:
        if type(value) is not str:
            raise TypeError("permitted verb must be an exact string")
        normalized = normalize_identifier(value)
        if (
            normalized != value
            or not is_safe_identifier(normalized)
            or "*" in normalized
            or len(normalized.encode("utf-8")) > MAX_VERB_ID_BYTES
        ):
            raise ValueError("permitted verbs must be bounded safe concrete identifiers")
        canonical.add(normalized)
    return tuple(sorted(canonical))


def _matches(pattern: str, verb_id: VerbId) -> bool:
    """Match one grant pattern against a verb id (K-9 terminal-wildcard rule).

    Both sides are NFKC-normalised first, and a verb id that is not a SAFE
    identifier never matches - so a Unicode-confusable verb id cannot impersonate
    an ASCII verb to slip past a grant (UPLOAD-05 / AZ-02)."""
    if not is_safe_identifier(verb_id):
        return False  # a non-canonical / confusable id can never be authorised
    pattern = normalize_identifier(pattern)
    verb_id = normalize_identifier(verb_id)
    if pattern == "*":
        return True
    if pattern == verb_id:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]  # drop the trailing ".*"
        # ``jira.*`` matches ``jira.read`` (next char is a boundary) but not ``jirax.read``.
        return verb_id == prefix or verb_id.startswith(prefix + ".")
    return False


@dataclass(frozen=True)
class GrantSet:
    """An immutable set of allow/deny verb patterns held by a caller."""

    allow: tuple[str, ...] = ()
    deny: tuple[str, ...] = ()

    @classmethod
    def of(cls, allow: list[str] | None = None, deny: list[str] | None = None) -> GrantSet:
        return cls(allow=tuple(allow or ()), deny=tuple(deny or ()))

    def permits(self, verb_id: VerbId) -> bool:
        """True iff this set authorises ``verb_id``. Deny-dominant, fail-closed."""
        if any(_matches(p, verb_id) for p in self.deny):
            return False  # K-5: deny dominates, short-circuit
        if any(_matches(p, verb_id) for p in self.allow):
            return True
        return False  # K-13: nothing matched -> deny

    def intersect(self, other: GrantSet) -> GrantSet:
        """Tenant ∩ skill grants. Allows must be permitted by BOTH; denies union.

        This is how an ephemeral's effective grants are computed: a skill cannot
        widen authority beyond what the tenant permits (US-IAM-04).
        """
        allow = tuple(p for p in self.allow if other.permits_pattern(p))
        deny = tuple(set(self.deny) | set(other.deny))
        return GrantSet(allow=allow, deny=deny)

    def permits_pattern(self, pattern: str) -> bool:
        """Whether this set would permit everything a pattern could match.

        Conservative: an allow ``*`` covers anything; otherwise the exact
        pattern (or a covering wildcard) must be present and not denied.
        """
        if any(_matches(p, pattern.rstrip(".*")) for p in self.deny):
            return False
        if "*" in self.allow:
            return True
        if pattern in self.allow:
            return True
        # a held wildcard that covers the requested pattern's prefix
        if pattern.endswith(".*"):
            return any(a == pattern or a == "*" for a in self.allow)
        return any(_matches(a, pattern) for a in self.allow)


# A frequently-needed sentinel: grants nothing (fail-closed default).
EMPTY_GRANTS = GrantSet.of(allow=[], deny=[])


@dataclass(frozen=True)
class TenantPermissions:
    """A tenant's ceiling of permitted verbs (from role mappings / manifest)."""

    tenant_id: str
    grants: GrantSet = field(default_factory=lambda: EMPTY_GRANTS)
