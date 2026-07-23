"""The dev/prod wall for the trusted Codex runtime ([2026] VJS-CC-VJS 2, D1; 7, J8).

What this wall actually protects: the per-cell model bearer is minted against the
cell's process identity, so it must never be minted for an identity the kernel
did not attest. The court ruled the lane lawful ONLY behind a wall that makes
the attestation gap structurally unreachable. There are now TWO postures that
discharge that, and this module admits exactly those two:

(a) The legacy single-operator DEV posture: ``BOLTRIG_DEV_AUTH=1`` and NO real
    ingress posture (OIDC / Cloudflare Access / session login). One trusted
    operator on one box is the isolation argument; the cell environment is
    observed, not kernel-attested, so nothing multi-user may share the box.

(b) The kernel-ATTESTED posture: per-cell uids are verifiably in force
    (``per_cell_uid_mode_available`` - the dropped API holds the live spawner
    socket the privileged entrypoint handed it). Under per-cell uids the
    identity the bearer is minted against is no longer observed, it is
    kernel-attested end to end: the ingress registers each App Server with its
    real uid (``registry.register(expected_uid=...)``), the SO_PEERCRED
    credentials of every connecting auth-helper are tied to a captured ancestor
    whose uid must EQUAL the registered cell uid (J8,
    ``model_proxy_peer_ancestry._registration_matches_process``), and issuance
    re-proves the cell's privilege state (J5). A cell of one uid therefore
    cannot be minted a bearer scoped to another, whatever the HTTP edge's auth
    mode is - so a real ingress posture (session login included) may COEXIST.
    The edge authenticates users; it is not an input to cell identity.

BOTH postures still require the explicit ``BOLTRIG_CODEX_TRUSTED`` flag (off by
default) and BOTH refuse under any production/staging signal: this wall never
flips a production gate. ``CodexAgentRuntime.production_ready`` stays False and
the runtime runs under the existing ``allow_test_only_runtime`` gate (D4); the
court-gated ``production_ready`` flip ([2026] VJS-CC-VJS 4 F9, 5 G1) is a
separate question this module does not touch.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from boltrig.config import Settings, load_settings, production_signal
from boltrig.fleet.infrastructure.cell_privilege import per_cell_uid_mode_available


class CodexTrustedPostureError(RuntimeError):
    """The process is not in a posture where the trusted Codex runtime is lawful."""


def require_codex_trusted_posture(
    env: Mapping[str, str] | None = None,
    settings: Settings | None = None,
    *,
    per_cell_uids: bool | None = None,
) -> None:
    """Fail closed unless a lawful trusted-Codex posture holds (see module docstring).

    Requires ``BOLTRIG_CODEX_TRUSTED`` always and refuses any production signal
    under either posture, then admits EITHER the legacy dev posture (a) OR the
    kernel-attested per-cell-uid posture (b). ``per_cell_uids`` overrides the
    probe only in tests; production callers leave it None so the answer is the
    verified runtime state, never a caller's claim.
    """
    e = env if env is not None else os.environ
    s = settings if settings is not None else load_settings(e)
    if not s.codex_trusted:
        raise CodexTrustedPostureError(
            "trusted Codex requires BOLTRIG_CODEX_TRUSTED=1 (off by default)"
        )
    signal = production_signal(e)
    if signal is not None:
        raise CodexTrustedPostureError(
            f"trusted Codex refuses to run under a production signal ({signal}); "
            "production_ready stays False under BOTH postures ([2026] VJS-CC-VJS 2 "
            "D4, 4 F9)."
        )
    real_ingress = (
        s.oidc_configured or s.cf_access_configured or s.session_auth_configured
    )
    if s.dev_auth and not real_ingress:
        return  # (a) the legacy single-operator dev posture
    attested = (
        per_cell_uid_mode_available(env=e) if per_cell_uids is None else per_cell_uids
    )
    if attested:
        return  # (b) the kernel-attested per-cell-uid posture
    if real_ingress:
        raise CodexTrustedPostureError(
            "trusted Codex refuses a real ingress posture (OIDC / Cloudflare Access / "
            "session login) without kernel-attested per-cell uids "
            "([2026] VJS-CC-VJS 2 D1, 7 J8)."
        )
    raise CodexTrustedPostureError(
        "trusted Codex requires BOLTRIG_DEV_AUTH=1 (single trusted operator) or "
        "a verified per-cell-uid posture (kernel-attested cell identity, "
        "[2026] VJS-CC-VJS 7 J8)."
    )


__all__ = ["CodexTrustedPostureError", "require_codex_trusted_posture"]
