# Character constitutions

A constitution is the **design authority** behind a character: what it believes,
how it argues, when it defers. What SHIPS is the compact prompt each document
ends with, copied into that character's `character.json` as `prompts.system`,
because a bundle's text is paid for on every turn. When the compact version says
something and nobody can remember why, the answer is in the long document.

| character | source document | shipped prompt |
| --- | --- | --- |
| Familiar | [familiar.md](familiar.md) | `apps/worker/src/bundles/familiar/character.json` |
| Colossus | [colossus.md](colossus.md) | `apps/worker/src/bundles/colossus/character.json` |
| Jarvis | not in the repo | `apps/worker/src/bundles/jarvis/character.json` |
| Ultron | not in the repo | `apps/worker/src/bundles/ultron/character.json` |

**Jarvis's and Ultron's source documents are not here.** Their compact prompts
were taken from constitutions supplied in the same shape as this one, and the
originals were not committed at the time. The prompts in their bundles are the
authority until the documents are restored; this row is a gap, recorded rather
than papered over, because "the long documents live in docs/characters" is the
claim `tests/test_persona_layer.py` makes about all of them and it is currently
only true of one.

**Familiar's document arrived titled "CLAUDE VOICE".** That title was wrong and
its author said so when supplying it. The body is kept verbatim — it is an
authored artefact — with the correction recorded at the top of the file and the
runtime-config block's `identity.name` set to `Familiar`, since that field is
read rather than read about. The rename also settles the clean-room boundary the
document raises in its own section 1: it asks not to be presented as Anthropic's
official Claude voice, and shipping it as a character with its own id, body and
voice, in a product that is not Anthropic's, satisfies that on the strictest
reading.

**She previously carried no persona, and the absence was itself a tested claim.**
`test_familiar_still_carries_no_prompts` argued that requiring a prompt of every
character would force INVENTING a personality for the one character that exists
to catch that assumption. That argument does not survive a supplied constitution.
The test is now `test_a_persona_is_still_OPTIONAL_in_the_schema`, which pins the
property that actually mattered — the format does not demand a persona, so the
next body that genuinely has nothing to say is still expressible — and no longer
depends on any particular character staying silent.

## How a constitution reaches a model

Three hops, and until recently the last one did not exist:

1. **The document** lives here. It is authority, not runtime text.
2. **The compact prompt** is copied into that character's `character.json`.
   `scripts/gen_personas.py` reads every shipped bundle and writes
   `boltrig/fleet/personas.py` — a generated table, because the kernel ships
   without the worker's tree and cannot read the bundles at runtime.
   `tests/test_chat_persona.py` fails if the two disagree.
3. **The turn** picks it up from the user's `agent.character` setting, in
   `boltrig/fleet/chat_persona.py`, and prepends it to the turn task.

**An id crosses the wire, never prose.** The set of personas is fixed at build
time, so a caller cannot supply persona text and cannot reach one that was not
shipped. An unrecognised id resolves to no persona rather than raising.

**It is a setting, not a request field.** A character is a user preference
rather than a property of one message, so the voice is the same on every
surface — chat, voice, a queued turn, a scheduled routine — instead of only
where a client remembered to send it.

For a long time step 3 was missing entirely: `compose_system_prompt` had no
production caller and the lane that runs sends pinned birth instructions
resolved once at import. Nothing failed, because a persona nobody reads looks
exactly like a persona working.

## What a constitution may never do

The persona layer is appended BELOW everything that carries authority — the
governance floor and the tier character — in `boltrig/fleet/prompt_stack.py`.
A character shapes prose and cannot widen what an agent may do. Grants, HITL
gates and consequence classes are enforced at the kernel's Dispatcher
chokepoint, which has never read a word of any of these documents.

That ordering is adversarially tested: `tests/test_persona_layer.py` hands the
composer a persona that tries to cancel the cage and asserts the cage is still
there and still first. Both constitutions that discuss it ask for precisely
this — Ultron's says "the runtime must enforce these restrictions independently
of the prompt; do not rely on the Ultron personality to police itself."

## Characters are governed agents, not special cases

Every character is a general execution agent under one governance model. A
constitution proposing its own containment profile, its own verbs or its own
authority model describes a character governing itself, and none of that is
implemented. Where a document asks for it, the deviation is recorded at the top
of that document rather than left for a reader to discover by its absence.
