# Decision 0023: an LLM does not decide what a human was asked to decide

**Status:** REFUSED, settled. **Occasion:** the Hermes Quicksilver crib, 2026-08-07.
**Scope:** the HITL approval gate only. This says nothing about using a model to
summarise, rank, explain or pre-fill an approval.

## What was on offer

Hermes v0.19.0 "Quicksilver" made an LLM reviewer the **default** judge of flagged
commands (#62661). A command that would previously have paused for a human is
instead read by a model, which decides whether it is safe, and the human is not
asked. It is a good trade for the product it ships in: one operator, their own
machine, their own blast radius, and the friction of confirming every flagged
command is the single loudest complaint such a tool gets.

boltrig is invited to adopt it because the friction is real here too.

## Why it is refused

boltrig's claim is not that its agents behave well. It is that **authority
decisions are made by a mechanism a court can inspect** - fail-closed dispatch
against explicit grants, one chokepoint, an approval bound to one canonical action
by fingerprint, single-use, and an audit trail that can be read back. A model's
opinion of a command is not that kind of mechanism. It cannot be enumerated in
advance, it does not produce the same answer twice on the same input, and when it
is wrong there is nothing to point at except a sampled token.

Substituting it for the human would put a probabilistic component **on the exact
seam the gate exists to hold**. Every other part of this system is arranged so
that the probabilistic parts propose and the deterministic parts dispose; decision
0018 refuses to re-drive a transcript to recover an approved call for precisely
this reason, calling it "the probabilistic failure the record exists to remove".
Admitting a model as the approver would reintroduce it one layer up, at the layer
that matters most.

Upstream's own runtime briefing (§9) records that the engine has no native RBAC,
no audit and no signed-skill governance, and that its `pre_tool_call` hook is
**fail-open**. That is a coherent design for a single-operator tool. It is also
the exact sentence boltrig's architecture was written to answer, so importing the
approval model from that design imports the assumption underneath it.

## What is NOT refused

- A model **summarising** what a pending approval will do, so the human decides
  faster. The decision stays with the human; only the reading is assisted.
- A model **flagging** that something looks unusual, raising consequence and
  causing MORE approvals. Raising a gate is always safe; the addon consequence
  hint already works this way and can only raise, never lower.
- Reducing approval volume by **narrowing what is gated** - a governed, reviewable
  change to policy, made once and in the open, rather than a judgement made per
  command by a model nobody can interrogate afterwards.

The friction is a real cost and the answer to it is the third bullet. Fewer things
gated, decided deliberately, beats the same things gated and quietly waved through.

## What WAS taken from it

Hermes scopes a verdict to the exact command rather than to a pattern, so a later
command matching the same shape gets its own review. That is correct and worth
confirming rather than assuming, so it was checked rather than asserted:

`approval_request_fingerprint` (`boltrig/kernel/hitl_fingerprint.py:42`) binds an
approval to `{tenant, noun, verb, params, initiator identity, run_id, grants,
skills_loaded, resource_context}`. Full params, not a pattern. The initiator, so
another actor cannot spend it. The resource context, so an approval does not
survive the thing it acts on changing - that is the `re_pended` outcome in
`held_write_resume`. Redemption goes through `consume_approved_by`, single-use.

A search for an auto-approve, an always-allow, a remembered decision or an
approval cache across `boltrig/` returns nothing. So boltrig is already where
Quicksilver moved to on this point, and further: Hermes scopes to the command,
boltrig also scopes to who asked and to what the resource looked like at the time.

## Reopening this

Not by preference, and not by accumulated friction - that is what this record is
for. It takes a Principal instruction or a court ruling, and either should engage
with the paragraph above about probabilistic components on the deciding seam
rather than with the volume of approvals.

Related: decision 0018 (held-write resume), [2026] VJS-PC 20 (the Codex sole
runtime orders), `docs/decisions/0017-trusted-codex-postures.md`.
