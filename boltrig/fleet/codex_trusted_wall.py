"""The dev/prod wall for the trusted Codex runtime ([2026] VJS-CC-VJS 2, D1).

The trusted read-only Codex runtime mints a per-cell model bearer from the child's
real process identity WITHOUT the SO_PEERCRED cross-check. The court ruled that
lawful ONLY when it is hard-walled from production: it must require dev-auth AND a
dedicated trusted flag AND fail closed under any production/staging signal or any
real ingress posture (OIDC / Cloudflare Access / session login). This module is
that wall, and it is called both where the trusted provider is constructed and
again inside ``build_runtime`` so the runtime is structurally unreachable under any
production signal.

It never flips a production gate: ``CodexAgentRuntime.production_ready`` stays
False and the runtime runs under the existing ``allow_test_only_runtime`` gate for
its stated single-box purpose (D4). This is a strict superset of the checks
``refuse_dev_auth_in_prod`` already trusts.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from boltrig.config import Settings, load_settings, production_signal


class CodexTrustedPostureError(RuntimeError):
    """The process is not in a posture where the trusted Codex runtime is lawful."""


def require_codex_trusted_posture(
    env: Mapping[str, str] | None = None,
    settings: Settings | None = None,
) -> None:
    """Fail closed unless the trusted read-only Codex posture holds ([2026] VJS-CC-VJS 2 D1).

    Requires ``BOLTRIG_DEV_AUTH`` and ``BOLTRIG_CODEX_TRUSTED``, and refuses under any
    production/staging signal or any configured real ingress posture. Raising here is
    the whole point: a wrong posture must never reach a bearer mint.
    """
    e = env if env is not None else os.environ
    s = settings if settings is not None else load_settings(e)
    if not s.dev_auth:
        raise CodexTrustedPostureError(
            "trusted Codex requires BOLTRIG_DEV_AUTH=1 (single trusted operator only)"
        )
    if not s.codex_trusted:
        raise CodexTrustedPostureError(
            "trusted Codex requires BOLTRIG_CODEX_TRUSTED=1 (off by default)"
        )
    signal = production_signal(e)
    if signal is not None:
        raise CodexTrustedPostureError(
            f"trusted Codex refuses to run under a production signal ({signal}); "
            "it mints a bearer without SO_PEERCRED and is lawful only off production "
            "([2026] VJS-CC-VJS 2)."
        )
    if s.oidc_configured or s.cf_access_configured or s.session_auth_configured:
        raise CodexTrustedPostureError(
            "trusted Codex refuses to run with a real ingress posture "
            "(OIDC / Cloudflare Access / session login) configured."
        )


__all__ = ["CodexTrustedPostureError", "require_codex_trusted_posture"]
