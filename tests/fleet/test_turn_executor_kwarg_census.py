"""Every optional kwarg the production executor takes is one the filter knows.

``turn_executor_compat`` drops kwargs a legacy injected executor cannot accept.
Its own docstring says "anything threaded into the executor call belongs in this
set the same day" - and the set has now been missed TWICE. First ``origin``
(2026-07-28), recorded in that file: every legacy-signature executor raised
TypeError, ``_safe_exec`` degraded rather than raised, and the turn answered
"(turn error: TypeError)" with nothing saying why. Then ``caller_context``
(2026-08-19), which failed four integration tests and then hung.

A rule stated in a comment and broken twice is a rule that needs an instrument.
"""

from __future__ import annotations

import inspect

from boltrig.fleet.chat_turn_execution import build_turn_executor
from boltrig.fleet.turn_executor_compat import _OPTIONAL_KWARGS

# The parameters every executor has always taken. Anything the production
# executor declares BEYOND these is newer than the legacy contract, so a legacy
# injected executor will not have it and the filter has to know to drop it.
_LEGACY_CORE = frozenset(
    {
        "tenant_id",
        "user_id",
        "role",
        "grants",
        "conversation_id",
        "run_id",
        "message",
        "relay",
        "attachments",
    }
)


def test_the_compat_filter_knows_every_newer_kwarg_the_executor_takes():
    executor = build_turn_executor(kernel=None, spawner=None)

    declared = {
        name
        for name, p in inspect.signature(executor).parameters.items()
        if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
    }
    newer = declared - _LEGACY_CORE

    unknown = sorted(newer - _OPTIONAL_KWARGS)
    assert not unknown, (
        f"{unknown} reach the executor call but turn_executor_compat does not "
        "know to drop them for a legacy signature. Add them to _OPTIONAL_KWARGS. "
        "Skipping this is not a lint failure: a legacy executor raises TypeError, "
        "_safe_exec degrades instead of raising, and the turn answers with a "
        "generic error that names nothing."
    )


def test_the_census_is_not_vacuous():
    """If the executor's signature stopped being readable, the check above would
    pass by finding nothing. Pin that it really sees the newer kwargs."""
    executor = build_turn_executor(kernel=None, spawner=None)

    declared = set(inspect.signature(executor).parameters)

    assert _LEGACY_CORE <= declared, "the legacy core moved; update this census"
    assert "caller_context" in declared and "origin" in declared
