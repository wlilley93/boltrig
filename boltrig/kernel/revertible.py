"""Effects that carry their own inverse (K-1 companion, after Cordis).

WHY THIS EXISTS. The kernel already reverses things -- `_unpublish_owned_verbs`
in config/control_lifecycle.py undoes what `KernelRegistry.register_adapter_verbs`
did -- but the inverse lives in a different module from the effect and is
maintained by hand. Two consequences, both observed:

  * THEY DRIFT. Deactivation honours an ownership convention (only touch a
    binding whose ``target_ref`` is this adapter) that registration did not,
    so the inverse was more careful than the effect it reversed.
  * THEY ARE INCOMPLETE. A hand-written undo reverses what its author
    remembered. It cannot reverse what it displaced, because nobody recorded
    what was there before.

Cordis's paper (`A Programming Paradigm for Spatiotemporal Composability`,
2026) calls the fix *revertible effects*: every context transformation carries
an inverse the runtime preserves, so removing a component removes its effects
exactly. This is that idea at the size this codebase needs it -- no framework,
no runtime, ~60 lines -- applied where the kernel actually mutates shared state.

WHAT IT DOES NOT DO. It is not a transaction and does not pretend to be. Revert
is best-effort compensation after the fact: if the process dies mid-way the log
dies with it, and if an inverse itself fails the remaining inverses still run
so one bad undo cannot strand the rest. Anything needing atomicity wants the
store's transaction, not this.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

log = logging.getLogger("boltrig.kernel.revertible")


@dataclass(frozen=True)
class Effect:
    """One applied change, and the exact inverse that undoes it.

    ``describe`` is for humans reading a log; ``revert`` is the whole point.
    The inverse is built AT APPLY TIME, when what was displaced is still known
    -- which is the difference between "delete the binding" and "put back the
    binding that was there before, including the case where there was none".
    """

    describe: str
    revert: Callable[[], Awaitable[None]]


@dataclass
class EffectLog:
    """Applied effects in order, newest last.

    LIFO ON REVERT, and that ordering is load-bearing rather than tidy: effects
    nest, so a later effect may depend on an earlier one still being in place.
    Undoing oldest-first would pull the ground out from under inverses that have
    not run yet.
    """

    effects: list[Effect] = field(default_factory=list)

    def record(self, describe: str, revert: Callable[[], Awaitable[None]]) -> None:
        self.effects.append(Effect(describe=describe, revert=revert))

    def __len__(self) -> int:
        return len(self.effects)

    async def revert(self) -> list[str]:
        """Undo everything, newest first. Returns what could not be undone.

        A FAILING INVERSE DOES NOT STOP THE REST. The alternative -- abort on
        first failure -- leaves the caller half-reverted with no record of which
        half, which is strictly worse than finishing and naming the casualties.
        The log is emptied either way, because an inverse that has run must
        never run twice.
        """
        failures: list[str] = []
        pending = list(reversed(self.effects))
        self.effects.clear()
        for effect in pending:
            try:
                await effect.revert()
            except Exception as error:  # noqa: BLE001 - reported, never raised
                log.warning("revert failed: %s: %s", effect.describe, error)
                failures.append(f"{effect.describe}: {error}")
        return failures
