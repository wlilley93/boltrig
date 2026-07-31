# [2026] VJS-CC-BOLTRIG-D7-DISCHARGE-001

**County Court at boltrig, First Instance (single judge).**
Convened 2026-07-31 on the advocate's own motion
(SUBMISSION-2026-07-31-170419, CONVENING-county-2026-07-31-170433).

**The question.** Does the Principal personally relaying the drafted D7 notice to
the client discharge D7 of [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001, whose
checkable is a `channel_outbox` row addressed to the client - and if so, what
evidence stands in the record in its place?

## Disposition

**D7 is VARIED, not waived.** The relay discharges the duty; the checkable is
substituted, and the substitution is chosen by this court, not by the party the
directive burdens. Two conditions replace the outbox row, and D7 closes only when
both exist.

## The judgment

The advocate was right to refuse to substitute the evidence himself and to bring
the question here instead. That refusal is the first thing to say, because it is
the whole difference between a varied order and an eroded one: **a checkable may
only be moved by the court that set it.** The submission candidly argued both
ways, and the court decides on the stronger halves of each.

**The duty is the telling; the checkable is the proof.** D7's own text settles
this. The directive orders the act "put to the party it was taken from" - that is
the duty - and then names the row as what would satisfy the court that it
happened. The sentence "a hitl_requests row that expired unheard satisfies
nothing" is dispositive: a row can exist while the duty goes unperformed, and the
original order already refused to accept one such row. The row was never the
point. It was the best machine-verifiable proxy available on the facts as they
stood, when the contemplated route ran through the stack.

**The route has lawfully changed, and the original route is now worse on every
axis the order cares about.** The Principal - the accountable officer of the
party that owes the duty - will put the notice into the client's hands through
the channel she actually uses with him. Against that, a `channel_outbox` row is:
in tension with the standing instruction against email to this client (F3);
producible without delivery only through a loopback whose own conditions
correctly refuse it on this tenant (F4); and, if delivered and ignored, exactly
the expired-unheard shape the original order rejected (F5). Insisting on the row
now would be honouring the proxy over the thing it proxied.

**But the substitution the advocate proposed for the FOR case is refused as
insufficient on its own.** A dated repository record that "the Principal says he
sent it" fails the property that made the original checkable worth writing: the
client could discover an outbox row from her own deployment's tables; she cannot
discover a file in a repository she has never seen. This jurisdiction's whole
method is that prose is not enforcement, and a variation that lands on prose
would be this court committing the defect the checkable existed to prevent. The
AGAINST case wins this limb.

**The cure is to keep both properties.** The stack can record, in the client's
own tenant database, that the notice was relayed - without sending anything. The
host-boundary security stream exists for exactly this class of act
(`write_host_boundary_security_event`, precedented by every `mint-token` and by
D6 of the original order): an append-only, tamper-evident row in HER deployment,
written by the host boundary, naming what was relayed (by digest), when, and by
what channel class. That row is selectable from the cv tenant database - the
original checkable's verification act, preserved - and it asserts the RELAY, not
a delivery the stack never performed, so it stays honest in precisely the way
[2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001 C4 demands of records: it says
what happened, never more.

## The ratio

A directive's checkable proves its duty and is not the duty. Where the route the
checkable assumed becomes unavailable or a lawful route performs the duty more
fully, the court may vary the checkable - but only to another machine-verifiable
record of equal or greater discoverability to the protected party, never to
prose, and only the court may make the substitution. A party burdened by a
directive who performs the duty by another route must return for the variation
before claiming discharge, exactly as happened here.

## The varied directive

D7 of [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001 now closes when BOTH exist:

**D7-V1 (the relay, the Principal's act).** The Principal relays the drafted
notice (`docs/findings/2026-07-31-cv-client-notice-D7.md`, pinned by sha256 at
the moment of relay) to the client through his own channel, and states so - with
the date and the channel class - for the record. The notice must be relayed
substantially as drafted; a summary of it is not it.

**D7-V2 (the row, the stack's act).** A host-boundary security event is written
on the cv tenant: `reason="d7_notice_relayed"`, subject the client identity the
notice concerns, detail carrying the notice's sha256, the channel class, the
relay date as stated by the Principal, and the audit sequence range (262-266)
the notice discloses. Checkable exactly as the original was: a select on the cv
tenant database returning that row. It is written only AFTER D7-V1 - a row
asserting a relay that has not happened would be the inverse of the
expired-unheard defect and worse than it.

The carried-over sentence stands with its force intact: a repository note with
no corresponding tenant row satisfies nothing.

## Obiter

The court notes, without deciding, that the standing instruction against email
to this client (F3) is the Principal's own and is untouched: the relay channel
is his choice, and nothing in this variation requires or licenses any send by
the stack. The reserved question from DEV-EGRESS-LOOPBACK-001 - what
`Tag:Not Dev` should default to - remains reserved.
