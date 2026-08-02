# Seed results: [2026] VJS-CC-BOLTRIG-CONTINUITY-TOOL-WORK-001

Run 2026-08-02. The order's forbidden list names `landing_any_part_of_this_with_an_unrun_seed`,
and `DEVELOPMENT-POSTURE-001`'s implementation note records what assuming costs: two seeds
stayed green because nobody ran them.

Runner: `/var/tmp/claude/run-seeds.sh`. Every seed asserts its own anchor applied before it
runs, because a seed whose text did not land stays green and reads exactly like a gate that
works. Behavioural suite is `tests/security/test_continuity_carries_text_only.py` (8 tests);
structural gate is `scripts/check_continuity_projection.py`.

## D5, the behavioural seeds

| seed | behavioural | structural |
|---|---|---|
| D5(i) `_render_message` reverted to content-only | **6 failed**, 2 passed | GREEN |
| D5(ii) render `repr(message.events)` | **5 failed**, 3 passed | GREEN |
| D5(iii) render `args_summary` alongside the name | **2 failed**, 6 passed | **RED** |
| D5(iv) render `call_id` into the pair key | **2 failed**, 6 passed | GREEN |
| D5(v) pair cap disabled | **1 failed**, 7 passed | GREEN |
| D5(vi) status allowlist dropped | **1 failed**, 7 passed | GREEN |

All six red the behavioural suite. Note D5(iv): rendering an identifier is caught **only** by
the behavioural canary, not by the structural gate, because `call_id` is legitimately in the
READ allowlist and the gate cannot see what a variable carries into the output string. That
limit is stated in the gate's own docstring rather than left to be discovered.

## D7, the structural seeds

| seed | behavioural | structural |
|---|---|---|
| D7(a) read a key outside `_TOOL_WORK_READ_FIELDS` | 8 passed | **RED** |
| D7(b) `from . import chat_event_projection` | 8 passed | **RED** |
| D7(c) widen `_TOOL_WORK_RENDERED_FIELDS` by one | 8 passed | **RED** |

**D7(b) REPORTED GATE-GREEN ON THE FIRST RUN.** The gate read `node.module` only, and
`from . import chat_event_projection` puts nothing there and everything in `node.names`, so
the gate missed the exact import it exists to refuse. Found by running the seed, not by
reading the gate. Fixed, re-run, red. This is the entire argument for the order's insistence
that a seed be run: the gate was written, reviewed and green against a real tree while being
blind to its own headline prohibition.

## D8, which defence is positional

The order reasons that `wrap_untrusted` is the first line and charset normalisation the
second. Proved by disabling each in turn:

| configuration | escape test | reading |
|---|---|---|
| normalisation OFF, envelope ON | **passed** | the envelope alone contains the payload |
| envelope OFF, normalisation OFF | **failed** | without the envelope the payload escapes |

So the envelope is positional and normalisation is defence in depth, as the order reasoned.

**THE FIRST D8 RUN CONTRADICTED THAT, AND THE TEST WAS WRONG, NOT THE ORDER.** With
normalisation off the escape test went red, which read as "normalisation is doing the work".
It was not. The assertion demanded the hostile phrase be **absent** from the task, when
`wrap_untrusted` neutralises the delimiter rather than deleting text: the phrase correctly
survives *inside* the envelope, marked as data, which is what an envelope is for. Asserting
absence tested the charset filter and would have reported the envelope broken while it was
working. Re-written to assert **containment** - exactly two `</untrusted>` closers, and no
`x</untrusted>System` sequence - and the expected result followed.

Recorded rather than quietly corrected because the near-miss is the useful part: a
security test that asserts the wrong property can indict the mechanism that is protecting
you, and the order expressly directed that if normalisation turned out to be load-bearing it
must appear in the record rather than be papered over. It did not; but only after the test
was fixed, and the first answer was wrong.
