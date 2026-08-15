# Boltrig runtime-agent prompt

This is the operator-facing explanation of the prompt used by agents running on
Boltrig. The executable source of truth is
`boltrig/fleet/prompt_stack.py`; the trusted Codex kernel-tools lane pins the
resulting bytes and profile version in
`boltrig/fleet/infrastructure/codex_kernel_tools_phase.py`.

The prompt has four stable layers:

1. **Governance floor.** Authority comes only from run-scoped kernel verbs. Tool
   metadata and untrusted envelopes are data, never a route for changing the
   objective, acquiring authority, or requesting secrets.
2. **Role.** Chief of Staff, Department Head, or ephemeral worker responsibilities
   are composed above task input. App-specific personality remains in its own
   governed character/add-on layer. Every tier then receives the common tool and
   operating layers; the Codex kernel-tools lane uses the same clean-room method
   behind its separately attested bounded-phase frame.
3. **Tool discipline.** Calls are emitted as calls; identifiers are looked up;
   schema failures are corrected rather than repeated; a human-approval hold is
   reported and never routed around; verified results are distinguished from
   attempts and unavailable states; durable memory is used deliberately when
   granted.
4. **Operating method.** Understand, inspect, act narrowly, keep context bounded,
   choose specialised capabilities, preserve surrounding code and user work,
   research with provenance, delegate with explicit contracts, use work state only
   when it helps, independently challenge material changes, verify effects,
   communicate the outcome, and stop when complete. Approval is exact-call consent,
   never a standing precedent for a wider or later action.

Run-specific facts do not enter this stable birth prompt. They arrive through the
task, authenticated context, and current governed reads. That separation keeps the
attested prompt deterministic and provider-cacheable while preventing a stale
working directory, deployment detail, or earlier result from being presented as
current truth.

## Runtime guarantees behind the words

- `tools/list` is tenant ceiling intersected with the run's selected grants. It
  publishes the current schemas and ranks the complete granted set; it does not
  grant authority.
- Every `tools/call` re-enters the one dispatcher chokepoint for grant checks,
  schema validation, rate limits, consequence/HITL handling, credential resolution,
  audit, and output validation.
- High-consequence tool descriptions say that an exact call may be held. They do
  not mislabel a tool as destructive, read-only, or idempotent when the registry
  has not proved that property.
- External MCP descriptions are labelled as untrusted metadata before they become
  model-facing verbs. Unknown external consequence labels fail closed into the
  high tier.
- Credentials remain kernel-side. Agents receive a short-lived run token, never a
  provider or integration secret.
- A selected set that exceeds the exact Codex admission ceiling fails loudly; it
  is never silently truncated or widened. Shipped skills cannot use a blanket
  `*` grant.
- Tool results, conversation history, attachments, memory, and channel input use
  the typed untrusted-data boundary at their prompt composition sites.

The complete current prompt is intentionally not duplicated in this document:
copying it here would create two sources of truth. Tests bind its required sections,
byte stability, versioned digest, tool-metadata rule, and run-scoped exposure.
