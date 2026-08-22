"""Character personas: what a character sounds like, and nothing more.

A persona is PROSE. It shapes how an answer reads. It cannot widen grants, reach
a tool or change routing: it composes below the governance floor in
`prompt_stack`, and the Dispatcher that checks authority never reads it.

TWO SOURCES, ONE TABLE. The characters this build ships come from
`personas_shipped`, generated from the public bundles. Anything else registers
itself -- an out-of-tree character lives in its own repository, is installed
into the kernel venv, and calls `register_persona` at import. That is the same
inversion the web client uses for bodies: core states the contract and discovers
what is installed, and NOTHING HERE NAMES A CHARACTER IT DOES NOT SHIP.

The split matters because the generated half travels inside the kernel container
to every deployment. A private character's prompt in that file would be
published by the act of shipping.
"""

from __future__ import annotations

from .personas_shipped import SHIPPED

#: Every persona this process can resolve. Seeded from the shipped table and
#: extended in place by `register_persona`.
PERSONAS: dict[str, dict[str, str]] = dict(SHIPPED)


def register_persona(character_id: str, *, name: str, system: str) -> None:
    """Add an out-of-tree character's voice.

    Called at import by a package the deployment chose to install, the same way
    a private body calls `registerCharacter` in the client. Refuses to shadow a
    shipped character: an installed package quietly replacing Jarvis's voice
    would be a supply-chain change wearing a plugin's clothes.
    """
    key = character_id.strip().lower()
    if not key:
        raise ValueError("a persona needs a character id")
    if key in SHIPPED:
        raise ValueError(f"{key} is a shipped character; its persona is not overridable")
    if not system.strip():
        raise ValueError(f"{key} registered an empty persona")
    PERSONAS[key] = {"name": name, "system": system.strip()}


def persona_for(character_id: str | None) -> str | None:
    """The persona text for a character id, or None.

    None for an unknown id rather than an exception: a character that is not
    installed must cost the turn its voice and nothing else. The same rule the
    web client applies to a body it cannot draw.
    """
    if not character_id:
        return None
    entry = PERSONAS.get(character_id.strip().lower())
    return entry["system"] if entry else None
