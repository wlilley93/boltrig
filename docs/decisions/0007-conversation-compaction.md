# 0007 - Long conversations compact via append-only derived summaries

- Status: accepted
- Date: 2026-07-03
- Bound by: SEC-46 (continuity is deterministic + append-only / prefix stable),
  [2026] VJS-COUNTY 4 (regenerate froze message content; superseded turns are
  excluded from continuity)

## Context

Continuity composes a conversation's full verbatim transcript into every turn's
task. That is deterministic and prefix-stable (the gateway prompt cache stays
warm), but it grows without bound: a long thread pays to resend its whole history
every turn. We wanted to cap that cost WITHOUT rewriting history and without
breaking prefix-stability or the superseded-turn exclusion.

## Decision

Past a configured threshold, the composer sends

    [derived summary of older turns] + [recent verbatim tail]

instead of the whole history. The summary is DERIVED data, never a mutation of the
frozen message record.

- **A new append-only store: `conversation_summaries`.** A summary row covers the
  older LIVE messages of one conversation up to a boundary message id
  (`up_to_message_id`, with `covered_count`). The table is INSERT-only: a
  re-compaction appends a NEW row covering more messages, it never edits an old
  one. It is tenant + owner scoped through its parent conversation and RLS-scoped
  like `conversation_messages`; it is purged with the conversation on erasure
  (M11 / SEC-74). The frozen message history (`content` / `events` /
  `superseded_by`) is left completely intact - the summary is a derived VIEW, not
  an edit.

- **Policy is config-as-data on `ChatConfig`** with conservative NON-ZERO defaults:
  `compaction_threshold = 40` live messages, `compaction_keep_recent = 12` recent
  verbatim turns. On by default, but 40 messages is well clear of a short thread,
  so ordinary conversations are never compacted. Tighten-only like the attachment
  caps: a manifest may only LOWER the threshold (compact sooner) or keep FEWER
  recent turns, never grow the verbatim window past the code ceiling. `threshold: 0`
  disables it, restoring full-verbatim continuity exactly.

- **Prefix-stability is preserved between compactions.** With a fixed summary the
  composed task is `render_summary_block(summary) + render_transcript(tail)`. The
  summary block is byte-stable and the tail only ever grows by appending, so turn
  N's task stays a byte-prefix of turn N+1's - the gateway cache keeps hitting. The
  composer splits older-vs-tail by matching the summary's boundary message id, so a
  supersede in the tail does not shift the boundary. A NEW compaction (the tail
  regrew past the threshold) deliberately shifts the boundary and is a cache-cold
  event - the documented "until the next compaction" caveat.

- **Superseded turns stay excluded (SEC-92).** Both the summarised older set AND
  the verbatim tail are drawn from the already-superseded-filtered `live` set, so a
  regenerated-away reply is neither summarised into the summary nor present in the
  tail.

- **The summary re-enters the task as DATA.** It is derived from untrusted
  conversation bodies, so `render_summary_block` wraps it in a typed
  `wrap_untrusted(kind="conversation_summary")` envelope (M1 / SEC-72) - it is never
  instructions.

## Deriving the summary: deterministic first, model optional

The shipped summariser is DETERMINISTIC and offline (`summarize_messages`): a stable
role-tagged, whitespace-collapsed, truncated digest of the covered turns. Same
covered set always yields the same text, which is exactly what keeps the summary
block byte-stable and the whole feature testable with no model - mirroring the
department head's deterministic decomposition fallback (P9).

`ChatService` also accepts an OPTIONAL model `summariser` seam. Because its output
re-enters the task, wiring a model summariser through the ONE kernel chokepoint is
the caller's contract; if it fails or returns empty the deterministic summariser
stands in. No model summariser is wired by default, so there is no new runtime
dependency and the offline path is the tested one.

## Where derivation happens

Compaction is evaluated AFTER a turn is fully persisted (end of `handle_turn`, and
after a `regenerate_turn`), so the NEXT turn's continuity read can compose the
cheaper `[summary + tail]` form. A re-compaction gate only appends a new summary
when it would cover strictly MORE messages than the latest one, so the summary -
and therefore the composed prefix - stays byte-stable across the turns between
compactions.
