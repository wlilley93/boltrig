# 0037 - The per-run capability projection, and the one decision it needs

- Status: proposed
- Date: 2026-08-18
- Related: `docs/SPEC-capability-doctrine.md` (§7.E, §11.8, §11.10),
  [2026] VJS-CC-VJS 10 D3/D4, decisions 0031 and 0036

## Context

`MAX_KERNEL_TOOLS = 128` against 633 Opbox source operations is the merge's
hardest constraint, and the cliff is not hypothetical. The bound's own comment
records the measurement: 197 verbs registered on a live tenant with a ceiling of
`allow:["*"]`, so a run whose grants resolve to the wildcard is 197 against 128
and **every turn dies there**. Skills narrow it to ~74 today, which is the only
reason it does not bite.

Six parallel readers established why §7.E cannot be built as written (SPEC
§11.10). What remains available is the compiled projection: select the run's
tools before admission rather than failing when there are too many. The mechanism
already exists and was built for this - `tool_disclosure.compute_tool_offer`
ranks by skill affinity, grant specificity, consequence and identifier, and takes
a `budget`. Its own docstring says: "When a budget is adopted it is passed here
and nowhere else."

## The decision this needs, which is not an implementer's to take

Adopting a budget means TRUNCATING the offer, and [2026] VJS-CC-VJS 10 D4
reserves the choice of a truncation size as a policy question. The same docstring
adds that "a wiring commit is the wrong place to settle it".

It is also not a local change. `_compile_codex_tool_ceiling` is documented as
"byte-for-byte the kernel MCP face's `tools/list` derivation ... so the
admission-compiled proxy ceiling and the tools the kernel will actually
advertise to the cell are the same set". So a budget applied to one must be
applied to the other, and the MCP face serves every consumer, not only Codex
cells. Truncating there changes what every model on every surface is offered.

The size itself, though, is not free. 128 is an attestation bound the lane
already enforces: above it the turn does not degrade gracefully, it dies. So the
real question put to the order is narrow:

> Is truncating a ranked offer to the bound the lane already refuses to exceed
> preferable to failing the turn outright at 129?

The argument for yes: the model gets 128 relevant tools instead of zero and a
degraded turn, the ranking is authority-neutral (D3 already settled that
disclosure only ever reduces what a model sees, never what it may do), and every
dropped tool remains permitted by the same grants - nobody's authority changes.
The argument for caution: it is still a silent reduction unless the drop is
announced, and it lands on every surface at once.

## Decision (proposed, not taken)

1. `_compile_codex_tool_ceiling` and the MCP face both select through
   `compute_tool_offer` with the SAME budget, threading the run's skills into
   the ceiling compile so the ranking has its strongest signal.
2. The budget is `MAX_KERNEL_TOOLS`, on the argument above.
3. A truncated projection is ANNOUNCED - counts, never names (K-20: a count is
   not content) - so a smaller tool table is never something an operator has to
   infer from a model behaving oddly.

## What was done now, and what was deliberately not

NOT taken: no budget is adopted, nothing truncates, and no behaviour changed.

DONE: `tests/unit/test_tool_surface_parity.py` now asserts that the two
derivations produce the same set, which was previously a claim in a docstring
with nothing enforcing it. That test is the precondition for step 1 above -
the moment either side starts selecting, the other must select identically, and
the two ways of getting it wrong are both silent:

- ceiling narrower than the offer: the model is shown a tool it may call and
  `model_proxy_tool_ceiling` drops the call from the request body with no error
  and no log;
- ceiling wider than the offer: the run carries authority for a tool the model
  is never told about.

A mutation that makes the ceiling drop one namespace turns the test red naming
both sides of the difference.

## Consequences

- The cliff remains. A tenant crossing 128 still loses the turn, which is the
  honest current state and is now recorded rather than discovered.
- Whoever takes the decision inherits a safety net rather than a bare
  instruction, and the change becomes small: a budget argument in two places.
