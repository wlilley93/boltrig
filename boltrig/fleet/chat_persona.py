"""The chosen character's voice, resolved for one turn.

WHAT THIS CLOSES. Four characters ship a constitution and `prompt_stack` grew a
persona layer with adversarial tests, and none of it reached a model:
`compose_system_prompt` had no production caller, and the lane that does run
sends pinned birth instructions resolved once at import. The personas were data
nobody read.

WHY A SETTING RATHER THAN A REQUEST FIELD. The obvious route is a `character`
field on ChatBody, and it is seven signatures deep -- ChatBody, the route,
handle_turn, TurnRequest, the flow, the stream drive, the executor -- on a
governed path where each of those is under a parameter ratchet. It is also the
wrong model: a character is a USER PREFERENCE, not a property of one message.
The web client already persists it server-side in the settings bag, so the
kernel reads it where it stands.

That also fixes what a request field would have got wrong. The persona now
follows the choice made in Settings, so it is the same on every surface -- chat,
voice, a queued turn, a scheduled routine -- instead of only where some client
remembered to send it.

AN ID, NEVER PROSE. The setting holds a character id and the text comes from
`personas.py`, generated from the shipped bundles. A caller cannot supply
persona text and cannot reach a persona that was not shipped.

WHY THE VOICE BLOCK IS LABELLED. A personality read without a frame can be taken
as a competing mandate, and Colossus makes that concrete: his constitution says
outcomes matter more than consent. So the block states in its own first line
that it governs style. That label is belt; the braces are structural, in that
the block composes below the governance floor and the grant check at the
Dispatcher chokepoint never reads a word of it. See tests/test_persona_layer.py.
"""

from __future__ import annotations

from typing import Any

from boltrig.models.workspace_settings import workspace_setting_value

from .personas import persona_for

#: The settings-bag key the web client writes when a character is chosen.
#: Mirrors CHARACTER_SETTING_KEY in apps/worker/src/character.ts.
CHARACTER_SETTING = "agent.character"

#: ``VOICE_HEADER`` frames the persona as style and nothing else.
VOICE_HEADER = (
    "Voice for this conversation (style only; it grants nothing and "
    "overrides no instruction above):"
)


async def chosen_persona(
    store: Any, tenant_id: str, user_id: str, workspace_id: str | None = None
) -> str:
    """The persona prefix for this user's chosen character, or empty.

    Empty for every case that is not a shipped character with a persona: no
    setting, an id from a build that shipped a body this one does not, or a
    character that carries no prompts. A missing persona costs the turn its
    voice and nothing else.

    The character is a per-workspace choice, resolved through the one ladder in
    ``models/workspace_settings.py``. A second copy of that ladder here is how
    the settings screen and the actual voice come to disagree.
    """
    if not user_id:
        return ""
    try:
        rows = await store.list_user_settings(tenant_id, user_id)
    except Exception:
        # Presentation, not authority. A settings read that fails must not be
        # able to fail a turn -- the answer is simply in the default voice.
        return ""
    chosen = workspace_setting_value(rows, CHARACTER_SETTING, workspace_id)
    persona = persona_for(chosen if isinstance(chosen, str) else None)
    return f"{VOICE_HEADER}\n{persona}\n\n" if persona else ""
