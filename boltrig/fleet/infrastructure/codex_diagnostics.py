"""Content-free cause reporting for codex runtime failures.

Its own module for two reasons. ``codex_agent_runtime`` sits at its structural
ratchet, so the diagnostic had to live somewhere it would not buy that file new
debt; and the rule below is one rule, applied identically wherever a codex failure
is caught, rather than a phrase re-derived at each handler.

THE RULE. A caught exception's TYPE is a class name from our own stack, and an App
Server error ``code`` is an int the protocol layer deliberately preserves. Neither
is model output, tool arguments, user text, or a secret, so both are safe to log
(K-20). ``str(exc)`` and ``exc_info`` are NOT: a ``JSONDecodeError`` carries the
offending document in its args, which is precisely the content the rule excludes.

Why it matters: ``codex_agent_runtime`` had no logger at all and raises
``from None``, which severs ``__cause__``. A model-proxy 401, a turn-spec schema
mismatch, an App Server timeout and a cell that died mid-RPC were byte-identical -
one fixed string, no cause. A tenant's agent failed every turn for an hour on that.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def log_operation_failure(op: str, exc: BaseException) -> None:
    """Name the cause of a codex runtime operation failure. ``op`` is a static label."""
    code = getattr(exc, "code", None)
    logger.warning(
        "codex runtime operation failed: op=%s cause=%s.%s code=%s",
        op,
        type(exc).__module__,
        type(exc).__qualname__,
        code if isinstance(code, int) else "-",
    )


def log_pump_crash(exc: BaseException, *, terminal_already_set: bool) -> None:
    """Report a notification-pump crash at the level its role deserves.

    WARNING when the crash is the CAUSE. When a terminal already exists the turn has
    already ended and the pump is simply blocked on next_notification() against a
    connection that has gone, raising ProtocolStateError("connection is closed") on
    the way out; the first terminal correctly wins. Logging THAT at WARNING fires on
    every healthy turn, and an alarm that cries wolf on the happy path is the same
    blindness as no alarm at all.
    """
    logger.log(
        logging.INFO if terminal_already_set else logging.WARNING,
        "codex notification pump crashed: %s.%s (terminal_already_set=%s)",
        type(exc).__module__,
        type(exc).__qualname__,
        terminal_already_set,
    )
