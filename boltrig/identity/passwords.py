"""First-party password hashing ([2026] VJS-COUNTY 7, D4).

Passwords are hashed with argon2id (the memory-hard PHC winner) via argon2-cffi.
The at-rest representation is the standard PHC-format encoded string
``$argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>`` - it embeds a fresh per-user
random salt (D4: "hash + per-user salt") and every cost parameter, so the stored
value is self-describing and never reversible. The plaintext is never stored, is
never logged, and never enters the audit chain (the audit writer scrubs it, K-20).

Verification is written to be constant-time in the sense that matters for an
authentication oracle: a login for an absent user still spends a full argon2
verify against a fixed decoy hash (``verify_dummy``) so response timing cannot
reveal whether an email exists (D5).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, VerifyMismatchError

# One shared hasher. Defaults are argon2-cffi's OWASP-aligned parameters
# (t=3, m=64MiB, p=4); kept as the library default so an upgrade tracks upstream.
_PH = PasswordHasher()

# A minimum-length floor so accept-invite cannot set a trivially weak password.
# Deliberately not an elaborate composition policy (which pushes users to
# predictable patterns); length is the property that actually resists guessing.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024  # a sanity cap so a huge input cannot become a DoS via argon2

# A fixed decoy hash used to equalise timing on the absent-user path (D5). It is a
# real argon2id hash of an opaque value nobody can present, so verifying against it
# always fails but costs the same as a genuine verify.
_DUMMY_HASH = _PH.hash("boltrig-constant-time-decoy-value-not-a-real-password")


class WeakPassword(ValueError):
    """The proposed password did not meet the minimum policy (length floor)."""


def validate_password_strength(password: str) -> None:
    """Raise :class:`WeakPassword` if ``password`` is unacceptable (D1/D4).

    The message is safe to surface to the setter (it is their own password), but
    carries no information about any other account.
    """
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise WeakPassword(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise WeakPassword("password is too long")


def hash_password(password: str) -> str:
    """Return the argon2id PHC-encoded hash of ``password`` (D4).

    A fresh random per-user salt is embedded by argon2-cffi. The caller must have
    already run :func:`validate_password_strength`; this function does not log or
    return the plaintext.
    """
    return _PH.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    """Whether ``password`` matches the stored argon2 ``encoded`` hash (D4/D5).

    Never raises on a mismatch - returns ``False`` - so callers can branch without
    a timing/exception side channel. A ``None``/empty stored hash returns ``False``
    but the caller should prefer :func:`verify_dummy` on the absent-user path so
    the argon2 cost is still paid.
    """
    if not encoded:
        return False
    try:
        return _PH.verify(encoded, password)
    except VerifyMismatchError:
        return False
    except Argon2Error:
        # A corrupt/foreign hash string is treated as a non-match (fail-closed),
        # never as an error that could distinguish it from a wrong password.
        return False


def verify_dummy(password: str) -> None:
    """Spend a full argon2 verify against the decoy hash and discard the result.

    Called on the absent/deactivated-user login path so the response timing is
    indistinguishable from a real (failed) verify - defeating a username-oracle
    timing attack (D5). Any outcome is ignored.
    """
    try:
        _PH.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, Argon2Error):
        pass
