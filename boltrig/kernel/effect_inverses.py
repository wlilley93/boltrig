"""How a verb declares its inverse - and the fail-closed default when none does.

THE CONTRACT. ``inverse_for(verb, params, output)`` answers with the exact
inverse invocation ``(inverse_verb, inverse_params)`` or ``None``. None is not
an error: it is the honest answer for a sent email, a completed payment, or
simply a verb nobody has annotated yet - and the ledger records those as
``not_undoable`` so the undo surface can say "this step cannot be undone"
instead of pretending.

WHY A REGISTRY AND NOT A GUESS. The kernel cannot derive that
``slack.message.send`` reverses through ``slack.message.delete`` with the
posted message's ``ts`` - only the verb's author knows, and only the SUCCESS
OUTPUT carries the identifiers the inverse needs. So a builder runs at record
time, with the params and the output in hand (the same apply-time rule
``kernel/revertible.py`` states: build the inverse while what was displaced is
still known), and returns concrete parameters that will still make sense when
the revert runs hours later.

Builders are registered by adapters/addons at composition; the map ships
EMPTY, so every verb starts not-undoable and coverage grows verb by verb
without a single lying default.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

#: builder(params, output) -> (inverse_verb, inverse_params) | None.
#: A builder may itself answer None (e.g. the output lacks the id the
#: inverse would need) - that specific call is then not-undoable.
InverseBuilder = Callable[
    [dict[str, Any], dict[str, Any]], tuple[str, dict[str, Any]] | None
]

_BUILDERS: dict[str, InverseBuilder] = {}


def register_inverse(verb_id: str, builder: InverseBuilder) -> None:
    """Declare ``verb_id``'s inverse builder. Last registration wins, which is
    the same rule adapter re-registration follows for the verbs themselves."""

    if not verb_id or not callable(builder):
        raise ValueError("an inverse registration needs a verb id and a builder")
    _BUILDERS[verb_id] = builder


def inverse_for(
    verb_id: str, params: dict[str, Any], output: dict[str, Any] | None
) -> tuple[str, dict[str, Any]] | None:
    """The inverse invocation for this successful call, or None = not undoable.

    Fail-closed twice over: an unregistered verb is None, and a builder that
    RAISES is treated as None rather than failing the call it decorates - the
    original invocation already succeeded, and losing it to bookkeeping would
    be worse than an honest not-undoable row.
    """

    builder = _BUILDERS.get(verb_id)
    if builder is None:
        return None
    try:
        return builder(dict(params), dict(output or {}))
    except Exception:
        return None
