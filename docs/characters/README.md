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
| Jarvis | [jarvis.md](jarvis.md) | `apps/worker/src/bundles/jarvis/character.json` |
| Ultron | [ultron.md](ultron.md) | `apps/worker/src/bundles/ultron/character.json` |

**Every shipped character's document is now here, and the bundle is checked
against it.** `test_the_bundle_carries_its_document_section_VERBATIM` asserts
each bundle's `prompts.system` is exactly the fenced section its document names.
That test exists because both ways of getting it wrong actually happened:

- **Drift.** Jarvis's and Ultron's prompts were written from an earlier reading
  of constitutions that were not committed at the time. When the documents
  arrived on 2026-08-17 they did not match -- Jarvis at 0.37 similarity, Ultron
  at **0.05**, which is not compression but a different text.
- **Truncation.** Colossus's prompt was extracted with a fixed line slice that
  stopped ten lines short of his section's end. The lines it dropped were the
  safety tail: the list of things he may not do, and the closing "You may reason
  as World Control. The runtime remains in control." The shipped character
  carried the doctrine without the limit.

Neither failed anything, and that is the point. A drifted prompt reads exactly
like a faithful one; a truncated prompt reads exactly like a complete one.

**Which section ships is data, not a convention.** The documents were authored
separately and number their core prompt differently -- Familiar §45, Ultron §25,
Jarvis §27, Colossus §48, and out-of-tree Maya §40 and Bella §46. The mapping
lives in one dict per side rather than in a rule nobody can check.

**A private character's constitution does NOT belong here.** `personas_shipped.py`
is generated from the bundles in this table and travels inside the kernel
container to every deployment, so a prompt placed here is distributed by the act
of shipping, whatever this repository's visibility. An out-of-tree character
keeps its document in its own repository and registers its voice by calling
`register_persona` at import — the same inversion `registerCharacter` provides
for bodies. Core states the contract; it names no character it does not ship,
and a deployment that has not installed that package has never heard of it.

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
   `boltrig/fleet/personas_shipped.py` — a generated table, because the kernel
   ships without the worker's tree and cannot read the bundles at runtime.
   `tests/test_chat_persona.py` fails if the two disagree. The registry that
   reads that table, `boltrig/fleet/personas.py`, is hand-written, because it
   carries the `register_persona` hook and a regeneration would overwrite it.
3. **The turn** picks it up from the user's `agent.character` setting, in
   `boltrig/fleet/chat_persona.py`, and prepends it to the turn task.

**An id crosses the wire, never prose.** The set of personas is fixed at build
time, so a caller cannot supply persona text and cannot reach one that was not
shipped. An unrecognised id resolves to no persona rather than raising.

**An out-of-tree character supplies its own.** `register_persona` refuses to
shadow a shipped character — an installed package quietly replacing Jarvis's
voice would be a supply-chain change wearing a plugin's clothes — but is
otherwise the whole extension point. Nothing in this repository lists what is
installed that way, which is the point of it.

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
