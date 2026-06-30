"""PII detection and redaction at the kernel boundary (US-PRIV-02, SEC-13).

A deterministic, model-free, network-free scan runs before any data is sent to
an external (non-local) model endpoint. Detected PII is redacted (default),
which the policy may upgrade to "route to a local model" (handled by the model
router). The same scanner backs audit scrubbing (K-20).
"""

from __future__ import annotations

import re
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
# hard block, not a redaction preference.
_SECRET_PATTERNS: dict[str, re.Pattern[str]] = {
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{20,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "bearer": re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    "password_kv": re.compile(r"(?i)(password|passwd|secret)\s*[=:]\s*\S+"),
}


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
    if _PATTERNS["email"].search(text):  # identity floor: a leaked email deanonymises
        return "email"
    return None
