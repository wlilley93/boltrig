"""On-behalf-of identity decisions and OBO token exchange (US-IAM-03/05, SEC-03).

A verb runs under one of two identity modes (S6.4):

  * ``service-principal`` - the platform acts as itself with its own adapter
    credential. The user is recorded for audit but the downstream call is the
    platform's.
  * ``delegated`` - the platform must act *as the user* downstream, so a user
    token is exchanged (OAuth 2.0 token exchange, RFC 8693) for a scoped
    downstream token. The exchange is a seam: a concrete exchanger is injected.

This module decides which mode applies and provides the exchange seam. It never
holds long-lived user secrets; a delegated token is minted per call and handed
to the kernel credential path, never returned to an agent (K-20).
"""

from __future__ import annotations

from typing import Awaitable, Callable

SERVICE_PRINCIPAL = "service-principal"
DELEGATED = "delegated"

# A seam: exchange a verified user token for a scoped downstream token.
TokenExchanger = Callable[[str, str], Awaitable[str]]


class OnBehalfOf:
    """Decides service-principal vs delegated and performs OBO exchange (SEC-03)."""

    def __init__(self, *, token_exchanger: TokenExchanger | None = None) -> None:
        self._exchanger = token_exchanger

    @staticmethod
    def is_delegated(identity_mode: str | None) -> bool:
        """Whether a verb's ``identity_mode`` requires acting as the user."""
        return (identity_mode or SERVICE_PRINCIPAL).strip().lower() == DELEGATED

    def mode_for(self, identity_mode: str | None) -> str:
        """Normalise a verb's identity_mode to one of the two canonical modes."""
        return DELEGATED if self.is_delegated(identity_mode) else SERVICE_PRINCIPAL

    async def exchange(self, user_token: str, scope: str) -> str:
        """Exchange a user token for a scoped downstream token (RFC 8693 seam).

        Raises if no exchanger is configured: a delegated verb must not silently
        fall back to the service principal (SEC-03), and exchange requires an
        IdP-specific token endpoint that the deployment injects.
        """
        if self._exchanger is None:
            raise NotImplementedError(
                "OBO token exchange is a seam; inject a token_exchanger. A "
                "delegated verb must act as the user and must not fall back to "
                "the service principal (SEC-03)."
            )
        return await self._exchanger(user_token, scope)
