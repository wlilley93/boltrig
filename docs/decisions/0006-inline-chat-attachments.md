# 0006 - Chat attachments are inline blobs on the message row

- Status: accepted
- Date: 2026-07-02
- Bound by: [2026] VJS-COUNTY 3 (chat attachments), [2026] VJS-COUNTY 4 (regenerate)

## Context

Chat turns needed to carry attachments (a pasted log, a small CSV, a screenshot).
The court held for the smallest thing that works: inline, size-capped attachments
carried as JSONB on the conversation message row, written and read only through the
existing message contract (`add_message` / `list_messages`). No object store, no
`StorageBackend`, no multipart upload seam, and no storage credential anywhere in
the chat or fleet layers.

## Decision

An attachment is a record `{name, media_type, data (base64), size}` stored inline in
the `conversation_messages.attachments` JSONB column. It is persisted as part of the
user message the turn creates, so it rides the same tenant-scoped, owner-scoped,
retention-and-erasure path as the message body itself.

- **Caps are typed policy-as-data on `ChatConfig`**, with conservative NON-ZERO code
  defaults (8 attachments, 256 KiB per attachment, 1 MiB total per turn, measured on
  DECODED bytes). A manifest may only TIGHTEN a cap below its default
  (`min(default, manifest)`), never loosen it.
- **Enforcement is fail-closed at intake**: an over-cap turn is rejected whole,
  before `add_message` and before any stream yield. Over-cap input is never
  truncated to fit.
- **Attachment content reaches the model only as data**: an agent-readable `text/*`
  attachment is enveloped via `wrap_untrusted(kind="attachment")` and appended to the
  task; every other media type persists record-only and is NEVER decoded into the
  task or the model input.

## Honest cost: this is an inline blob, not an object store

Storing the bytes inline in the row is a deliberate trade for simplicity and for
keeping the governance/retention story identical to the message body. The cost is
real and stated plainly:

- **Row growth.** Each attachment's base64 blob lives in the row. Base64 inflates
  the stored size by ~33% over the raw bytes. At the caps above, one turn's row can
  grow by up to ~1 MiB of decoded content (~1.33 MiB base64), and a
  `list_messages` read pulls every attachment blob of every message in the thread
  into memory. That is why the code defaults are deliberately small.
- **No dedup, no streaming, no lifecycle of its own.** Two turns that attach the
  same file store it twice; there is no range read and no separate expiry - an
  attachment is erased exactly when its message is (soft-close, then the retention
  hard-purge, SEC-74).
- **When to revisit.** If attachments ever need to be large, many, binary-heavy, or
  shared across messages, the right move is a real object-store seam behind the
  message contract (a `StorageBackend` reference on the record instead of the bytes)
  - a new court matter, not a silent widening of these caps. Until then, inline
  blobs on the row are the honest, bounded choice.
