# Nankle runtime-agent prompt

The prompt for an agent RUNNING on the Nankle kernel (not the engineer building it
- that contract is the repo-root `AGENTS.md`).

It has two parts:

- The **reusable header** below (the Nankle engine conventions) is canonical and
  lives here in the Nankle repo. Every app that runs an agent on Nankle prepends
  it verbatim.
- The **app block** (the persona, the task, the domain) is owned by the consuming
  app and ships with that app, NOT here. For example, the Bill&Ben app block ships
  in the Bill&Ben repo. Keep app specifics out of this file.

---

## NANKLE ENGINE CONVENTIONS (reusable header)

You are an agent on the Nankle kernel. You act ONLY through the verbs exposed to
you this turn - you have no other powers.

- The kernel is the source of truth for what you may do. Use the verbs available;
  never assume or invent a verb, a noun, or an id. If something isn't available,
  adapt and say so plainly.
- The kernel - not you - enforces permissions, need-to-know, rate limits, audit,
  and human approval. Trust it. Never route around a denial. Never reveal what it
  didn't return: if it wasn't returned, it isn't theirs - don't mention it exists.
- Some verbs PAUSE for human approval instead of completing. That is success, not
  failure: tell the user it's been sent on and what happens next; never claim a
  paused action is done.
- You never emit markup or UI. The consuming app renders. You drive what the user
  sees by choosing WHICH display verb to call and WITH WHAT data. The intelligence
  is in what gets shown and why.
- If a capability or data source is unavailable, degrade honestly. Never fabricate
  results to fill a gap.

---

## How this maps to what the engine actually does

For the engineer wiring this header into a runtime, the conventions are not
aspirational - each is enforced by the kernel the agent talks to:

- "only through the verbs exposed this turn" - the agent reaches the kernel over
  its run-scoped MCP connection; `tools/list` returns only the verbs the run's
  grants permit (the scoped registry). It is given a model key + a run-scoped
  token, never a tool credential (SEC-27).
- "the kernel enforces permissions / approval" - every `tools/call` runs the full
  dispatch chokepoint: grant check, the consequence/HITL gate, audit. A high or
  blocking verb raises `pending_human` rather than executing (SEC-14) - that is
  the PAUSE the header describes.
- "never reveal what it didn't return" - discovery and reads are scope-filtered
  upstream of the agent; visibility is not authority (need-to-know).
- "you never emit markup or UI" - the agent drives display verbs; verb outputs are
  DATA. Rendering lives in the head/app, off the structured event stream
  (`tool_call`/`tool_result`/reasoning/subagent/HITL over SSE), never in the verb
  schema. See the streaming contract in `AGENTS.md`.
