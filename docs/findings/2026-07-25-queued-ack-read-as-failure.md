# A durably-accepted chat message reported as a failure

Date: 2026-07-25
Status: Console and Node SDK FIXED. One sibling OPEN, deliberately, with the
reason recorded below.

## The defect

`POST /v1/chat` answers `202` with a `{"status": "queued", ...}` body when the
conversation already has a turn in flight: the message is durably queued as a
steer (US-CHAT-15) and is answered as the NEXT turn on that in-flight stream. It
is an acceptance, not a failure, and there is no stream for this caller to read.

Three clients got it wrong, in two different directions:

- **The console** swallowed it. `res.ok` is true for 202, so the SSE pump ran on a
  JSON body, found no `data:` frame, dispatched nothing and resolved. A queued
  message rendered as a turn that completed with no reply. Fixed: `streamChat`
  returns the ack, and the sender announces it.
- **`sdks/node/src/head.ts`** raised `request failed (HTTP 202)`. Fixed.
- **`boltrig/api/chat_cli.py`** raises `request failed (HTTP 202)`. **Still open.**

## Why the CLI one is still open

Not because it is acceptable. Because `boltrig/api/chat_cli.py` sits at exactly
400 lines, the structure gate's file limit, with no exemption. The fix needs the
202 branch plus a `render_event` arm (without one the CLI prints nothing at all,
which is a different lie), and there is no version of it that fits in zero lines.

The choice was: mint a new structural exemption for a file that has never needed
one, in order to land an out-of-scope sibling fix, or leave the sibling recorded
and let it be done as part of the split that file already needs. The second is
the smaller debt. It is written down here rather than left to be rediscovered.

This is also how I found that I had already broken the gate: I committed the
console fix WITH the chat_cli change and ran only `make ui-quality`, not `make
structure`, so a Python file went over the limit on main. Reverting the chat_cli
hunk restored it. The lesson is narrow and worth keeping: run the gate that
covers the language you touched, not the one that covers the change you think you
made.

## Adjacent, and not fixed here

The 202 branch now gates on `parsed.status === "queued"` rather than on the
status code, because 202 is not reserved to this ack: the kernel returns it for a
`pending_human` pause and for empty-bodied MCP notifications, and the SDK contract
says any high-consequence route may honestly answer 202. Coercing every 202 into
"queued" would have mislabelled those as queued steers.
