# Character constitutions

A constitution is the **design authority** behind a character: what it believes,
how it argues, when it defers. What SHIPS is the compact prompt each document
ends with, copied into that character's `character.json` as `prompts.system`,
because a bundle's text is paid for on every turn. When the compact version says
something and nobody can remember why, the answer is in the long document.

| character | source document | shipped prompt |
| --- | --- | --- |
| Colossus | [colossus.md](colossus.md) | `apps/worker/src/bundles/colossus/character.json` |
| Jarvis | not in the repo | `apps/worker/src/bundles/jarvis/character.json` |
| Ultron | not in the repo | `apps/worker/src/bundles/ultron/character.json` |
| Familiar | none, deliberately | none — she carries no `prompts` block at all |

**Jarvis's and Ultron's source documents are not here.** Their compact prompts
were taken from constitutions supplied in the same shape as this one, and the
originals were not committed at the time. The prompts in their bundles are the
authority until the documents are restored; this row is a gap, recorded rather
than papered over, because "the long documents live in docs/characters" is the
claim `tests/test_persona_layer.py` makes about all of them and it is currently
only true of one.

**Familiar's absence is not a gap.** She is a body with no persona, and her
bundle omits `prompts` entirely. `test_familiar_still_carries_no_prompts` pins
that: requiring a prompt of every character would force inventing a personality
for the one character that exists to catch exactly that assumption.

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
