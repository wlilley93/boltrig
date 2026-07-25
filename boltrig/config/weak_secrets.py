"""One predicate for "this secret is a placeholder, not a secret".

[2026] VJS-CC-BOLTRIG-AUDIT-KEY-PROVISIONING-001, O2. Before this module there
were TWO contradictory answers to that question and the gap between them was a
live hole:

- ``api/doctor.py`` knew ``change-me-to-a-long-random-secret`` is a placeholder,
  because it is one of the values the repo actually ships in ``.env.example``.
- The audit-key guard in ``api/bootstrap.py`` recognised only the IN-SOURCE
  default (``dev-insecure-audit-key``) and blank.

So the exact string a deployment gets by following the documented ``cp
.env.example .env`` tripped NEITHER the fatal nor the warning, and the audit
hash chain ran keyed by a public constant in this repository while reporting
itself tamper-evident. A guard that misses the value the project itself ships is
worse than no guard, because it reassures.

Anything deriving trust from a deployment secret asks HERE, so the answer cannot
drift again.
"""

from __future__ import annotations

# Exact values that are never a real secret. Lower-cased on comparison. Includes
# every placeholder this repository has ever shipped: `dev-insecure-audit-key`
# is the in-source fallback in kernel/audit.py, and the change-me forms are what
# .env.example carried.
PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "change_me",
        "changeme",
        "change-me",
        "change-me-to-a-long-random-secret",
        "dev-insecure-audit-key",
        "password",
        "replace",
        "replace-me",
        "secret",
    }
)

# Substrings that mark a value as un-filled-in even when the whole string is not
# an exact match (e.g. "prefix-CHANGE_ME-suffix").
PLACEHOLDER_FRAGMENTS = ("CHANGE_ME", "REPLACE", "example.com", "your-org")

# Shortest value we will treat as a real secret. A shorter one is either a
# placeholder or too weak to key an HMAC chain worth trusting.
MIN_SECRET_LENGTH = 24


def is_placeholder_secret(value: str | None) -> bool:
    """True when ``value`` is absent, a known placeholder, or obviously unfilled.

    Deliberately does NOT apply the length floor: some callers (the audit-key
    guard) must fail closed only on values that are demonstrably placeholders,
    so that a short-but-real key is a doctor warning rather than a boot failure.
    Use :func:`is_weak_secret` when the length floor is wanted too.
    """

    raw = (value or "").strip()
    if raw.lower() in PLACEHOLDER_SECRETS:
        return True
    return any(fragment in raw for fragment in PLACEHOLDER_FRAGMENTS)


def is_weak_secret(value: str | None, *, min_len: int = MIN_SECRET_LENGTH) -> bool:
    """True when ``value`` is a placeholder OR shorter than ``min_len``."""

    if is_placeholder_secret(value):
        return True
    return len((value or "").strip()) < min_len
