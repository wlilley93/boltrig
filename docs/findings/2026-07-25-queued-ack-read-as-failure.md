# A durably-accepted chat message reported as a failure

Date: 2026-07-25
Status: FIXED in Console, Node SDK and terminal Chat.

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
- **`boltrig/api/chat_cli.py`** previously raised `request failed (HTTP 202)`.
  Fixed by accepting only a JSON `202` whose status is exactly `queued` and
  rendering an explicit queued-behind-the-active-turn event. Other `202`
  responses remain errors.

## Why the CLI fix was split

`boltrig/api/chat_cli.py` was already at the structure gate's file limit. The
bounded HTTP-body interpretation now lives in `boltrig/api/chat_cli_http.py`;
the streaming and rendering behavior remains in the terminal client. No
structural exemption was added.

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
