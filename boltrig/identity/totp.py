"""First-party TOTP two-factor + one-time recovery codes ([2026] VJS-COUNTY 10).

The console second factor. Three secret classes live here, each with a HONEST
at-rest story:

  - the TOTP shared secret (a base32 string). It is SEALED via the credential
    store (``set_credential_ref``), the same RLS-fenced seam the channel signing
    secret and per-org AI keys use (D1). It is NEVER stored in a plaintext column
    on the identity row, NEVER written to audit, and returned to the client EXACTLY
    ONCE (the enroll-begin QR/secret), never again. Verification loads it kernel-
    side at challenge time and hands it straight to :func:`verify_totp`.

  - one-time recovery codes. Generated once at enrollment, shown ONCE, and stored
    ONLY as sha256 hashes (D2), mirroring the SEC-34 PAT / SEC-97 invite token seam
    (a high-entropy secret is fine to hash with sha256; argon2 is reserved for
    low-entropy passwords). Each is single-use (consumed atomically) and is a
    FALLBACK for a lost authenticator, never a bypass of the factor.

  - the login challenge token. A high-entropy opaque token minted after the
    password verifies, stored as its sha256 only, short-lived and single-use. It
    proves "the password already verified" without issuing a session (D3): the
    session is issued only when the second factor then verifies against it.

Verification is constant-time in the sense that matters for an auth oracle:
pyotp compares the candidate code with :func:`hmac.compare_digest`, and the
challenge path always spends a verify (a decoy on the absent-secret path) so
timing cannot reveal whether a secret/challenge exists (D5).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import pyotp

# The issuer label shown in an authenticator app (the "Boltrig (email)" entry).
TOTP_ISSUER = "Boltrig"
# RFC 6238 defaults (30s step, 6 digits, SHA1) - the near-universal authenticator
# baseline. verify accepts the adjacent window so a small clock skew still passes.
_TOTP_VALID_WINDOW = 1

# Recovery codes: ten codes, each 10 base32 chars (~50 bits) shown once. Enough
# entropy that a sha256 hash is not offline-guessable, matching the token pattern.
RECOVERY_CODE_COUNT = 10
# 26 symbols over a 32-char alphabet = 26 * log2(32) = 130 bits per code. A
# recovery code is stored only as an UNSALTED sha256, so on a table exfiltration
# its strength is its own entropy; 130 bits keeps it in line with the rest of the
# token seam (token_urlsafe(32)) and far out of offline-brute-force range, even
# with 10 codes per user. (The old 10-char / 50-bit code was GPU-crackable on a
# leak; a cracked code still needs a password-gated challenge token, but the
# entropy is raised regardless.)
_RECOVERY_CODE_LEN = 26
_RECOVERY_ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"  # base32-ish, no ambiguous 0/1/8/9

# The login challenge token: high-entropy, short-lived, single-use.
CHALLENGE_TTL = timedelta(minutes=5)

# A fixed decoy secret used to equalise timing on the absent-secret / absent-
# challenge path (D5): verifying a presented code against it always fails but
# costs the same as a genuine verify, so response timing carries no oracle.
_DECOY_SECRET = pyotp.random_base32()


# --- TOTP secret ------------------------------------------------------------
def generate_totp_secret() -> str:
    """A fresh RFC 4648 base32 TOTP shared secret (the sealed material)."""
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, account: str) -> str:
    """The ``otpauth://`` URI for the QR shown ONCE at enroll-begin.

    Encodes the shared secret, the issuer and the account (the user's email) so an
    authenticator app can enrol by scanning it. This is the one and only time the
    secret leaves the kernel; it is never returned again.
    """
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=TOTP_ISSUER)


def verify_totp(secret: str | None, code: str) -> bool:
    """Whether ``code`` is a currently-valid TOTP for ``secret`` (constant-time).

    Never raises - returns ``False`` for a missing secret or a malformed code - so
    callers branch without a timing/exception side channel. pyotp compares with
    ``hmac.compare_digest`` and ``valid_window`` tolerates a one-step clock skew.
    """
    if not secret or not isinstance(code, str):
        return False
    candidate = code.strip().replace(" ", "")
    if not candidate.isdigit():
        return False
    try:
        return pyotp.TOTP(secret).verify(candidate, valid_window=_TOTP_VALID_WINDOW)
    except Exception:
        # A corrupt/foreign secret is a non-match (fail-closed), never an error
        # that could distinguish it from a wrong code.
        return False


def verify_totp_dummy(code: str) -> None:
    """Spend a full TOTP verify against the decoy secret and discard the result.

    Called on the absent-secret / absent-challenge path so response timing is
    indistinguishable from a real (failed) verify - defeating an existence oracle
    (D5). Any outcome is ignored.
    """
    try:
        pyotp.TOTP(_DECOY_SECRET).verify((code or "").strip(), valid_window=_TOTP_VALID_WINDOW)
    except Exception:
        pass


# --- one-time recovery codes ------------------------------------------------
def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> list[str]:
    """Generate ``count`` fresh plaintext recovery codes (shown ONCE at enroll).

    The caller returns these to the user a single time and persists ONLY their
    hashes (:func:`hash_recovery_code`). Formatted ``xxxxx-xxxxx`` for legibility.
    """
    codes: list[str] = []
    for _ in range(count):
        raw = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(_RECOVERY_CODE_LEN))
        # Group into 5s for legibility (normalize strips the dashes before hashing).
        grouped = "-".join(raw[i:i + 5] for i in range(0, len(raw), 5))
        codes.append(grouped)
    return codes


def normalize_recovery_code(code: str) -> str:
    """Canonicalise a presented recovery code before hashing/compare.

    Lower-cases and strips whitespace + the display hyphen so the code a user types
    (with or without the dash, any case) hashes to the same value it was stored as.
    """
    if not isinstance(code, str):
        return ""
    return code.strip().lower().replace("-", "").replace(" ", "")


def hash_recovery_code(code: str) -> str:
    """The at-rest sha256 of a recovery code - never the plaintext (D2).

    Mirrors the invite/PAT/session token-hash seam. High-entropy input, so sha256
    is the right one-way form (argon2 is reserved for low-entropy passwords).
    """
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()


# --- login challenge token --------------------------------------------------
def generate_challenge_token() -> str:
    """A fresh high-entropy 2FA login challenge token (never stored raw)."""
    return "boltrig_2fa_" + secrets.token_urlsafe(32)


def hash_challenge_token(token: str) -> str:
    """The at-rest sha256 of a challenge token - never the token itself (D3)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
