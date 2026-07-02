"""PII detection and redaction at the kernel boundary (US-PRIV-02, SEC-13).

A deterministic, model-free, network-free scan runs before any data is sent to
an external (non-local) model endpoint. Detected PII is redacted (default),
which the policy may upgrade to "route to a local model" (handled by the model
router). The same scanner backs audit scrubbing (K-20).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

# Deterministic patterns. Conservative by design; a real deployment tunes these.
_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[ -]?)?(?:\(?\d{3}\)?[ -]?)\d{3}[ -]?\d{4}\b"),
    "ipv4": re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"),
}

# Secret patterns that must NEVER reach the audit record (K-20). These are a
# hard block, not a redaction preference. Ordered most-specific first so the
# reported kind is precise (M12: anthropic before openai; both keyed on ``sk``).
_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    # PEM private key blocks (RSA/EC/OpenSSH/DSA/PGP or bare) (M12).
    "pem_private_key": re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"
    ),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    # Stripe live/test secret + restricted keys (M12).
    "stripe_key": re.compile(r"(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{10,}"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    "password_kv": re.compile(r"(?i)(password|passwd|secret)\s*[=:]\s*\S+"),
}

# High-entropy fallback (M12): catch a secret whose shape we do not enumerate
# (an opaque base64/base64url token) without tripping on the hex hashes, UUIDs
# and ordinary prose that legitimately appear in audit rows / memory content.
# Candidate = a contiguous run of >= _ENTROPY_MIN_LEN base64-ish characters that
# mixes lowercase, uppercase AND a digit. That diversity gate alone excludes
# lower-hex SHAs/UUIDs (no uppercase) and alphabetic word-runs (no digit); the
# Shannon-entropy gate is the second line. Empirically SHAs/UUIDs/prose sit at
# ~3.2-3.8 bits/char while random base64 secrets sit at ~4.4-5.2, so a 4.0
# bits/char threshold separates them with margin. Runs on every audit row and
# memory ingest, so it stays a single findall + a cheap count over few matches.
_ENTROPY_MIN_LEN = 32
_ENTROPY_BITS_THRESHOLD = 4.0
_ENTROPY_CANDIDATE = re.compile(r"[A-Za-z0-9+/=_-]{%d,}" % _ENTROPY_MIN_LEN)


def _shannon_entropy(s: str) -> float:
    """Shannon entropy of ``s`` in bits per character."""
    n = len(s)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in Counter(s).values())


def _looks_high_entropy_secret(text: str) -> bool:
    """True if ``text`` contains a long, diverse, high-entropy opaque token (M12)."""
    for token in _ENTROPY_CANDIDATE.findall(text):
        has_lower = any(c.islower() for c in token)
        has_upper = any(c.isupper() for c in token)
        has_digit = any(c.isdigit() for c in token)
        if not (has_lower and has_upper and has_digit):
            continue  # excludes hex SHAs/UUIDs and alphabetic word-runs
        if _shannon_entropy(token) > _ENTROPY_BITS_THRESHOLD:
            return True
    return False


@dataclass(frozen=True)
class ScanResult:
    found: dict[str, int]  # type -> count
    redacted: str

    @property
    def has_pii(self) -> bool:
        return bool(self.found)


def redact(text: str) -> ScanResult:
    """Redact PII in ``text``, returning the redacted text and what was found."""
    found: dict[str, int] = {}
    out = text
    for name, pat in _PATTERNS.items():
        matches = pat.findall(out)
        if matches:
            found[name] = len(matches)
            out = pat.sub(f"[REDACTED:{name}]", out)
    return ScanResult(found=found, redacted=out)


def contains_secret(text: str) -> str | None:
    """Return the name of the first secret/identity pattern found, or None.

    Used by the audit writer to fail-closed (K-20): if this is non-None, the
    record must not be written verbatim."""
    for name, pat in _SECRET_PATTERNS.items():
        if pat.search(text):
            return name
    if _looks_high_entropy_secret(text):  # M12: opaque high-entropy token fallback
        return "high_entropy"
    if _PATTERNS["email"].search(text):  # identity floor: a leaked email deanonymises
        return "email"
    return None
