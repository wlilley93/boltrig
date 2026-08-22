# Chat display objects

Status: implemented in the open named-agent PR; not deployed or merged.

Boltrig chat can carry safe, model-authored visual objects without executing
model-authored UI code. A durable named agent calls `chat.present` with bounded
JSON. The kernel validates and stamps the object, the public chat projector
validates it again, the event is persisted with the assistant turn, and each
client validates it a third time before selecting a host-owned renderer.

“Novel” means a new composition of reviewed primitives. It never means arbitrary
React, JSX, HTML, CSS, JavaScript, an iframe, a remote component, or a model-chosen
action endpoint.

## End-to-end path

1. An interactive tier-1 named-agent turn receives the intrinsic `chat.present`
   grant and discovers the complete JSON Schema through its tool catalogue.
2. The dispatcher performs ordinary schema/grant/audit handling.
3. `ChatPresentAdapter` accepts only an interactive tier-1 context, stamps the
   actual run and agent address, applies safe template defaults, and publishes a
   `display_object` frame to the parent human-chat run.
4. The closed public projector drops undeclared frame fields and reduces an
   invalid object to a content-free `event_unavailable` notice.
5. Chat persistence stores the projected frame in the assistant message `events`.
6. The web SDK normalizer retains the object and its stream-order timeline entry.
7. Web, local, desktop and mobile chat render through the same registry. The
   browser parser rechecks version, kind, bounds, blocks, fields, URLs and
   coordinates before dereferencing anything.

Ephemeral subagents and asynchronous peer mailboxes are denied `chat.present`.
They cannot inject a card into an old or unrelated human turn. A named peer may
return information to its caller, and the named agent currently addressing the
human decides what to present.

## Version and catalogue

The envelope version is `boltrig.display.v1`. The catalogue contains 64 semantic
templates:

| Family | Templates |
|---|---|
| Content | Markdown, code, image, file, sources, gallery, artifact |
| Status | Notice, progress, steps, system, feedback, tool receipt, coordination, execution target, screen context, computer batch |
| Questions | Text, single/multiple choice, date/time, person, agent, connection, recipient, file, form, ranking |
| Confirmation | Simple, destructive, typed phrase, approval summary |
| Data | Table, key/value, metrics, chart, timeline, map, place, diff |
| Communication | Email, Slack, Teams, WhatsApp, Telegram and webhook draft/receipt pairs |
| Records | Issue/ticket, calendar, contact, document, Opbox entity/action, task, routine |
| Custom | Safe composition of reviewed blocks |

The canonical kind list is
`sdks/web/src/displayObjects.ts`. A parity test compares it with the kernel set so
the two catalogues cannot drift silently.

## Primitive library

`custom.card` and any template-specific `blocks` array may compose:

- safe text, GFM Markdown, code, notice and divider;
- key/value rows, metrics and bounded tables;
- progress, steps and timelines;
- accessible bar-style data series;
- HTTPS image, gallery and source links;
- text diffs;
- bounded latitude/longitude map links opened with OpenStreetMap.

Form fields cover text, textarea, number, date, datetime, select, multiselect,
person, agent, connection, recipient, checkbox and file intent. File fields direct
the user through the governed composer attachment path; a display object does not
gain a separate upload side door.

The current renderer deliberately uses an accessible data summary rather than
letting JSON select a charting package or arbitrary map provider. More reviewed
host components can be added behind the same versioned grammar.

## Editable communication drafts

The richer draft surface currently applies to email, Slack, Teams, WhatsApp and
Telegram:

- preview sender/workspace, recipient, subject/thread and body as appropriate;
- switch between preview and edit;
- focus and change the recipient;
- edit email Cc/subject and all message bodies;
- discard locally with an explicit “nothing was sent” state;
- keep Send disabled while the assistant response is still streaming;
- submit the exact edited object id, revision, connection/channel, recipient and
  body as a new turn in the same conversation.

Send does **not** call a provider from browser JSON. The new turn instructs the
same named agent to use the normal governed provider verb (`email.send`,
`channel.send`, or the relevant binding). Kernel grant, input schema, consequence,
HITL, credential resolution, idempotency and audit therefore remain in force. The
UI does not claim delivery until a real provider/tool receipt arrives.

This makes the workflow usable now while preserving Boltrig's one chokepoint. A
future direct one-click provider mutation requires a kernel-issued, short-lived
action token tied to exact object revision, principal, conversation, operation and
approval state. Model-authored `intent` is never sufficient authority.

## Questions and confirmations

Question templates can synthesize a sensible field from their kind and options or
accept an explicit bounded form. Required fields must be present before Reply.

Simple, destructive and typed confirmations record a precise new chat turn. Typed
confirmation requires the exact phrase. These cards are presentation-level review,
not substitutes for kernel HITL: a consequential action still crosses the normal
approval gate.

## Example: editable Slack draft

```json
{
  "kind": "slack.message.draft",
  "title": "Draft release update",
  "data": {
    "channel_id": "slack-primary",
    "workspace_label": "Acme",
    "recipient": "#launch",
    "thread_label": "Release candidate",
    "body": "The release candidate is ready for review."
  }
}
```

The kernel supplies default Edit, Change recipient, Send and Discard actions for
valid message drafts with an explicit channel/connection id.

## Example: novel launch-health card

```json
{
  "kind": "custom.card",
  "title": "Launch health",
  "data": {"summary": "Current readiness"},
  "blocks": [
    {
      "type": "metrics",
      "items": [{"label": "Ready", "value": "92%", "change": "+4%"}]
    },
    {
      "type": "table",
      "columns": ["Owner", "State"],
      "rows": [["Legal", "Ready"], ["Support", "Reviewing"]]
    },
    {
      "type": "map",
      "latitude": 51.5072,
      "longitude": -0.1276,
      "label": "London"
    }
  ]
}
```

## Trust and bounds

- Envelope keys are closed; kinds, statuses, field types, block types and action
  intents are enumerated.
- Encoded object size is at most 64 KiB; JSON depth, keys, arrays, fields, blocks,
  actions, strings, table dimensions and gallery/series sizes are bounded.
- Numbers must be finite. Coordinates and map zoom are bounded.
- Renderable URLs must be HTTPS, have a hostname and contain no credentials.
- `chat.present` discards all model-supplied provenance and stamps only the
  kernel-trusted run and agent. Provider/connection truth belongs to trusted
  provider receipts, not presentation JSON.
- All labels and values remain untrusted text. React escapes them; Markdown does
  not enable raw HTML.
- Invalid server frames do not reflect their payload into error text.
- Later revisions with the same object id replace earlier revisions within the
  displayed turn; duplicate older revisions do not render twice.

## Implementation map

- Kernel contract and defaults: `boltrig/models/display_objects.py`
- Primitive validation: `boltrig/models/display_object_blocks.py`
- Agent-facing schema: `boltrig/models/display_object_schema.py`
- Tool adapter: `boltrig/adapters/builtin/chat_present.py`
- Public event projection: `boltrig/fleet/chat_event_projection.py`
- SDK catalogue/parser/normalizer: `sdks/web/src/displayObjects.ts`,
  `displayObjectValidation.ts`, `chatTurnNormalizer.ts`
- Worker registry and cards: `apps/worker/src/components/chat/display/`

## Honest remaining work

- Cards currently render after the turn's prose/activity group; the SDK preserves
  original order, but full prose/tool/object interleaving is not yet rendered.
- Local draft edits are captured exactly when submitted but are not persisted as a
  separate durable display-object revision before submission.
- Direct action tokens, stale-revision rejection, expiry and one-click provider
  replay are not implemented.
- The first chart renderer is a bounded accessible bar summary; line/donut/area/
  scatter visualizations, pagination and server-backed data references remain.
- Domain record templates share the safe generic renderer; specialized ticket,
  calendar, Opbox and routine editors remain UI work.
- Visual regression, keyboard matrix, reduced-motion and narrow-device coverage
  should expand beyond the current interaction/unit tests.
- The branch has not been merged or deployed; none of this may be described as
  live on Beelink or production until release and live verification.
