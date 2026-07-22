"""At-rest envelope sealing for credential references (SEC-04, K-20).

The doctrine says the application DB holds *references* only - never plaintext.
In practice three writers (TOTP enrolment, per-org AI keys, legacy channel
signing secrets) hand ``set_credential_ref`` a dict carrying inline secret
material. This module makes the "no plaintext at rest" claim TRUE at the store
seam: every dict written through ``set_credential_ref`` is sealed into a
versioned envelope before it touches the DB, and transparently unsealed on
``get_credential_ref``. Writers and readers are unchanged; what rests in
``credential_refs.data`` is ciphertext.

Envelope format (a dict, so it round-trips the JSONB column and the memory
store unchanged)::

    {"sealed": "v1", "ct": "<fernet token>"}

``ct`` is a Fernet token (AES-128-CBC + HMAC-SHA256, authenticated) over the
canonical JSON of the original reference dict. The ``sealed`` marker makes
sealed rows distinguishable from legacy plaintext rows: a row WITHOUT the
marker is returned verbatim, so existing plaintext rows keep working
(read compatibility); any rewrite of the row re-seals it (lazy re-seal).

Keys (kernel-held, from the environment - never in the DB):

  - ``BOLTRIG_SEAL_KEY``: the active sealing passphrase. Any high-entropy
    string; the Fernet key is derived as SHA-256 of the passphrase, so
    operators supply a passphrase, not a pre-baked Fernet key. Generate with
    ``python -c "import secrets; print(secrets.token_urlsafe(48))"``.
  - ``BOLTRIG_SEAL_KEY_PREVIOUS`` (optional): the previous passphrase,
    honoured for DECRYPT ONLY, so a rotation is: set the new key as
    ``BOLTRIG_SEAL_KEY``, the old one as ``BOLTRIG_SEAL_KEY_PREVIOUS``,
    restart (old rows still unseal), and re-write rows to re-seal them under
    the new key lazily; then drop the previous key.

Rotation story is deliberately simple: ONE active key encrypts, an optional
previous key decrypts (``cryptography.fernet.MultiFernet``). There is no
per-row key id because there is at most one decrypt-only predecessor.

Production guard (mirrors ``refuse_default_audit_key_in_prod``, K-19): an
unset key falls back to the in-source ``dev-insecure-seal-key`` so offline
dev/tests just work, but under a production signal (same classification as
``boltrig.config.environment.production_signal``, duplicated here because the
SEC-54 stack boundary forbids the store layer importing ``boltrig.config``) a
missing or default key is FATAL. The check runs lazily at first seal/unseal so
the store layer stays import-safe and free of boot ordering; the failure is a
RuntimeError naming the signal, never the key.

The sealed envelope never contains plaintext, and unsealed material is only
ever returned through the kernel-side ``get_credential_ref`` seam - it is
never logged, audited, or handed to an agent.
"""

from __future__ import annotations

import hashlib
import json
import os
from base64 import urlsafe_b64encode
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from boltrig.models import CredentialResolution

# Envelope marker: ``{"sealed": _SEALED_VERSION, "ct": ...}``. Versioned so a
# future envelope change stays distinguishable from both v1 and legacy rows.
SEALED_VERSION = "v1"

_DEV_SEAL_KEY = "dev-insecure-seal-key"

# Mirrors boltrig/config/environment.py (production_signal / is_truthy). The
# store layer may NOT import boltrig.config (SEC-54 stack boundary: config is an
# upper layer, and its package __init__ reaches back into the kernel), so the
# tiny signal check is duplicated here - keep the two in lockstep.
_PRODUCTION_VALUES = frozenset({"prod", "production", "staging"})
_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "y", "t"})


def _production_signal(env: dict[str, str]) -> str | None:
    """Return the first explicit production/staging signal, otherwise ``None``."""
    if (env.get("BOLTRIG_PRODUCTION") or "").strip().lower() in _TRUE_VALUES:
        return "BOLTRIG_PRODUCTION"
    for name in ("ENV", "BOLTRIG_ENV", "APP_ENV"):
        value = (env.get(name) or "").strip().lower()
        if value in _PRODUCTION_VALUES:
            return f"{name}={value}"
    return None


def _passphrase_to_fernet(passphrase: str) -> Fernet:
    """Derive a Fernet key from an arbitrary passphrase (SHA-256, urlsafe-b64)."""
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return Fernet(urlsafe_b64encode(digest))


@lru_cache(maxsize=8)
def _fernets(key: str, previous: str | None) -> MultiFernet:
    """Build (and cache, keyed on the material itself) the active+previous set."""
    fernets = [_passphrase_to_fernet(key)]
    if previous:
        fernets.append(_passphrase_to_fernet(previous))
    return MultiFernet(fernets)


def _active_fernets(env: dict[str, str] | None = None) -> MultiFernet:
    """Resolve the kernel-held sealing keys, enforcing the production guard."""
    e = env if env is not None else os.environ
    key = e.get("BOLTRIG_SEAL_KEY")
    signal = _production_signal(e)
    if signal is not None and (not key or key == _DEV_SEAL_KEY):
        raise RuntimeError(
            f"FATAL: BOLTRIG_SEAL_KEY is unset/default with a production signal "
            f"({signal}). Credential references would be sealed with a public "
            "dev key - plaintext-equivalent at rest (SEC-04). Set a strong "
            "BOLTRIG_SEAL_KEY."
        )
    return _fernets(key or _DEV_SEAL_KEY, e.get("BOLTRIG_SEAL_KEY_PREVIOUS") or None)


def is_sealed(ref: dict[str, Any]) -> bool:
    """True when ``ref`` is a sealed envelope (of any known version)."""
    return isinstance(ref, dict) and ref.get("sealed") == SEALED_VERSION


def seal_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Seal a reference dict into its versioned envelope for at-rest storage.

    Idempotent: an already-sealed envelope is returned unchanged (so a store
    that re-persists a read-modified row never double-seals).
    """
    if is_sealed(ref):
        return ref
    payload = json.dumps(ref, sort_keys=True, separators=(",", ":")).encode("utf-8")
    token = _active_fernets().encrypt(payload).decode("ascii")
    return {"sealed": SEALED_VERSION, "ct": token}


def unseal_ref(ref: dict[str, Any]) -> dict[str, Any]:
    """Unseal an envelope back to the original reference dict.

    Legacy rows (no ``sealed`` marker - plaintext dicts written before sealing
    existed, or external-store references) are returned verbatim, preserving
    read compatibility. A tampered or wrong-key envelope FAILS CLOSED with
    ``CredentialResolution``; the error never carries ciphertext or key hints.
    """
    if not is_sealed(ref):
        return ref
    try:
        payload = _active_fernets().decrypt(ref["ct"].encode("ascii"))
        data = json.loads(payload.decode("utf-8"))
    except (InvalidToken, KeyError, AttributeError, ValueError) as exc:
        raise CredentialResolution(
            "sealed credential reference cannot be unsealed (wrong key or tampered row)"
        ) from exc
    if not isinstance(data, dict):
        raise CredentialResolution("sealed credential reference did not hold a dict")
    return data
