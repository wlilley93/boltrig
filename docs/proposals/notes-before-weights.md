# Notes before weights - the system-prompt-learning lane

Status: proposal, 2026-08-09. Companion to decision 0023 (sleep distillation);
deliberately NOT implemented in that cut because it touches the attested birth
profile, which is a doctrine surface.

## The idea

Karpathy's "system prompt learning" direction: much of what we reach for
weights to learn should first be learned as *editable notes the model reads* -
reversible, inspectable, diffable - and only what survives in the notes should
be consolidated into weights. Applied to Boltrig's sleep distillation:

```
   nightly:   day's record -> NOTES edit (bounded text, human-approved)
   weekly:    notes that survived + corpus -> register LoRA train
```

The weights lane already exists (0023). This proposal is the notes lane in
front of it, and the ordering claim: **a tone/behaviour observation lives in
notes for at least one cycle before any trainer sees it.** A note that keeps
getting corrected never reaches weights; a note that survives becomes
training-worthy signal. Weight updates stop being the first draft.

## Why this is a decision, not a feature

The natural home for the notes is the addon ``harness`` text
(`docs/addons.md`): bounded (<= 4096 bytes), appended BELOW the governance
floor so it can never override the cage, and compiled into the attested,
hashed birth profile. Those three properties are exactly why it is the right
container - and why writing to it nightly is doctrine-touching:

1. **Attestation.** The birth profile is hashed precisely so what an agent was
   born with is provable. A nightly self-edit means the hash changes nightly
   BY DESIGN - the attestation story must become "hash-chained sequence of
   profiles", not "one stable profile". That is a real change to what the
   attestation claims and needs its own ruling.
2. **Self-reference.** The agent proposing edits to its own standing
   instructions is the classic self-modification loop. The HITL gate makes it
   safe-ish (a human approves every edit), but the *pressure* is new: the
   thing under review is the reviewer's future disposition.
3. **The floor must stay legible.** The addon contract already warns that a
   long harness pushes the cage out of attention. A nightly accretion process
   is exactly how harness text bloats; the lane needs a hard byte budget and
   a compaction rule (supersede, never append-forever) from day one.

## Sketch (for the eventual ruling)

- `distill.notes.propose` (low): derive a candidate notes diff from the day's
  corpus - the same derivation discipline as 0023: from the governed record,
  erasure-filtered, PII-scrubbed, digest-pinned. Output is a DIFF against the
  current notes, bounded, keys-and-prose.
- `distill.notes.apply` (high, HITL): a human approves the diff; the applied
  notes version is hash-chained (prev_hash over the notes sequence, the audit
  pattern) and the addon harness re-compiles. Fail-closed: an unapproved diff
  expires.
- The register corpus builder gains one input: the note-survival ledger.
  Records contradicting a corrected-away note are down-weighted; behaviour
  captured in a surviving note for N cycles becomes eligible for the weekly
  register train.
- Erasure: notes are TEXT, so unlike weights they honour deletion directly -
  an erasure that touches a note's source conversations triggers a notes
  rebuild the same way it triggers a corpus rebuild.

## What this buys

- Most "personality drift" complaints become a `git diff` on notes instead of
  a forensic exercise over weights.
- The register LoRA trains on pre-validated signal, so the weekly cadence can
  stay conservative without the system feeling static day-to-day.
- A bad learned behaviour is reverted by editing text, not by retraining.

## Not in scope until the ruling

Automatic (non-HITL) note application; per-user notes; notes as a memory
substitute (facts still belong in Knowledge/memory - notes carry *dispositions*,
the how-to-be, not the what-is).
