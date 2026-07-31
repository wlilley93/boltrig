# Notice to Classical Visas (D7)

**Status: DRAFT, NOT SENT.** Nothing has left the stack. This is the text for the
Principal to relay through his own channel to the client, per his direction of
2026-07-31. See the note at the end on how that sits with the order's checkable.

Directive: **D7** of `[2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001`, which
requires the act to be put to the party it was taken from.

---

## The notice

Subject: two changes made to your Boltrig deployment on 29 July, for your record

Two things happened to the Classical Visas deployment on 29 July 2026 that you
should be told about directly rather than have to find.

**1. An approval that normally needs a second person was cleared by one.**

The system holds back any high-consequence action for a human to approve, and it
normally refuses an approval from the same person who asked for it, so that two
people are always involved. On 29 July at 10:23 UTC that independence requirement
was deliberately suspended on your deployment under a development setting, and the
request was approved by the same person who made it.

The action approved was the re-registration of an integration adapter. It is
recorded in your audit chain at sequence 265, verb
`hitl.development_posture_approval`, and the record explicitly carries
`development_posture: true` - it does not present itself as an ordinary two-person
approval.

That development setting has since been **withdrawn** from your deployment
(29 July, 16:27 UTC) and cannot be re-declared on it. Your deployment now requires
a genuinely independent approver for every high-consequence action.

**2. The number of operations the system can perform over your data increased.**

The same re-registration took the invocable surface from **99 operations to 443**.
Nothing was removed; the increase is the adapter publishing the full set of
operations it supports rather than the subset previously registered. The current
figure is 578, reflecting later, separately-recorded registrations.

The operations are all subject to the same controls as before: each is recorded in
the audit chain, and each high-consequence one still requires a human approval.
The change is in how much the system CAN be asked to do, not in what it may do
without asking.

**What you may want to do.** Nothing is required of you. If you would like the
full list of the 443 operations, or the audit chain entries for either event, they
can be produced. If you would prefer a narrower registered surface, that can be
reduced.

---

## The record behind each statement

| statement | evidence |
|---|---|
| approval cleared with no independent reviewer | `audit_log` seq **265**, 2026-07-29 10:23:17 UTC, verb `hitl.development_posture_approval`, detail `development_posture: true` |
| the action approved | `audit_log` seq **266**, verb `control.adapter.activate`, status `ok` |
| the request and the approver were the same person | seq 263 (`requested_by`) and seq 265 (responder) both `will.lilley93@gmail.com` |
| the posture is withdrawn | `boltrig-tenants/cv/manifest.yaml`, the block replacing the posture declaration, dated 2026-07-29, citing D1 |
| 99 -> 443 | the finding recorded in D7 of the order |
| current count 578 | `select count(*) from verbs` on `cvboltrig`, 2026-07-31 |

## How this sits with the order's checkable

DECIDED: **[2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001** (2026-07-31) varied D7 rather
than waiving it. The Principal's relay discharges the duty; the checkable is
substituted by the court with a pair that keeps the original's property (a row the
client can discover from her own deployment):

- **V1** - the Principal relays THIS notice, pinned by sha256 at the moment of
  relay, and states the date and channel class for the record. A summary of the
  notice is not the notice.
- **V2** - after V1, `scripts/record_d7_relay.py` writes a host-boundary security
  event on the cv tenant (`reason=d7_notice_relayed`) carrying the notice digest,
  channel class, relay date, and the audit range 262-266. Checkable exactly as the
  original was: a select on the cv tenant database returning that row.

The script requires the V1 facts and refuses blanks, so the pair cannot close out
of order. A repository note with no corresponding tenant row satisfies nothing.

Nothing has been sent. The standing engineering instruction against email to this
client is untouched by any of the above.

**For the Principal: when you have relayed it, say so with the date and the
channel class (e.g. "relayed 2026-08-01, in person"), and V2 runs then.**
