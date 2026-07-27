# Decision 0019: should the pump route an unaddressed item by INTENT?

**Status:** OPEN, and it is the Principal's. **Record id:** `PRINCIPAL-2026-07-27-ROUTE-BY-INTENT`.
**Raised:** 2026-07-27, by
[2026] VJS-CC-BOLTRIG-WORKFLOW-PROMOTION-TRIGGER-001 D8.
**Expiry:** 2026-10-31. On that date without an answer, the court's ratio applies with no
further order: retire.

## The matter

`WorkflowLibrary.match` selects a workflow by INTENT TAGS, ranking by overlap. It is reachable
from exactly one function, `select_or_generate_workflow`, and that function has no production
caller: every reference to it under `boltrig/` is its own definition and a package re-export.
Production selects a workflow by explicit id, through `control.workflow.trigger`,
`control.workflow.execute`, and the pump's addressed `workflow:<id>` target.

So the whole intent-based retrieval path, and the learning leg that would fill the library it
searches, exist and have never run.

The workflow-promotion subsystem that ranked within that path has been deleted under the order
above, because the value it produced had no consumer. Four names survive that deletion and are
waived against THIS record:

| name | where |
| --- | --- |
| `select_or_generate_workflow` | `boltrig/workflows/generator.py` |
| `WorkflowLibrary.match` | `boltrig/workflows/library.py` |
| `learn_from_success` | `boltrig/workflows/generator.py` |
| `_maybe_learn` | `boltrig/fleet/pump.py` |

## The question, in one sentence

**Should the pump's routing path consult the workflow library by intent, before routing an
unaddressed work item to the chief of staff?**

## Why it is the Principal's and not the court's

The court decided the question it was actually asked, and declined to defer it: there is no
"when does promotion run" decision, because on the current record every answer has identical
effect and, on the correct shape, the value is derived rather than triggered. It sent this
question up instead, and the distinction is the point.

Routing by intent changes **what runs for a tenant**. An unaddressed item that today reaches a
human-shaped chief of staff would instead be matched against a library of previously generated
workflows and executed. That is a product posture, not an engineering trade-off: it is a
statement about how much of a tenant's work should be handled by something the system taught
itself. No record before the court establishes a demand for it, and no measurement can supply
one, which is exactly the shape of a question an engineer must not answer by default.

## What an answer looks like

**Yes.** The pump gains an intent-match step before its chief-of-staff fallback. The four names
above get callers and the waiver is deleted. The rebuild rule from the order's limit L2 binds:
if promotion returns, the eval-gated state is **derived** at read time from the eval cases
targeting the workflow and their latest run, pinned by the definition's `build_workflow_snapshot`
digest so an eval that proved an earlier definition cannot rank a changed one. No promotion
table, no writer, no trigger.

**No.** The four names are deleted, `generator.py` and the learning leg go with them, and the
library becomes a store of workflows selected only by id.

**No answer by 2026-10-31.** Retire, per the order.

## What is NOT being asked

Whether the self-improvement flywheel is a good idea in principle. That was settled by
[2026] VJS-COUNTY 5, which is untouched: provenance may make a workflow more likely to be
reused and may never widen what it is permitted to do. This asks only whether the retrieval half
should be reachable at all.

## An honest note on that precedent

COUNTY 5 pinned the authority boundary "before the loop is extended", on a stated belief that
the loop was already live and already reusing learned artifacts. On today's record it never ran:
`GENERATED_WORKFLOW_KEY` is written by nothing, so the learning leg cannot fire either. The
ratio is unaffected and worth keeping in place over an inert path. But the bench was told a loop
was live because code existed and had callers, and no gate could contradict it. That is the same
defect the loop's own governance was convened to prevent, occurring in the convening.
