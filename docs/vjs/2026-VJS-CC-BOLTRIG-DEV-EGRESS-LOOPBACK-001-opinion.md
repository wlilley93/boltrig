# [2026] VJS-CC-BOLTRIG-DEV-EGRESS-LOOPBACK-001

**Court of First Instance (1 judge). Convened 2026-07-31 on the advocate's own
motion, at the Principal's direction.**

**Matter.** May the stack, under a development tag enabled on the stack by the
Principal, divert governed outbound egress (`channel.send`) away from its declared
external recipient and into a webhook the stack itself receives?

---

## holding

**Permitted, on five conditions, ALL of which must hold before the diversion may
run once.** The relief sought is narrower than it first appears and the risk runs
in the opposite direction to the posture cases: this does not widen what may
leave the system, it prevents anything leaving at all. That is why it is granted.
It is granted **conditionally** because the same property that makes it safe -
nothing reaches the recipient - is a lie told to the approver unless the record
says so at the moment of approval.

The advocate pleaded this as an independence question. **It is not one**, and the
court declines to decide it on that ground.

---

## ratio

**A control may be narrowed by a declared posture where the narrowing removes the
protected exposure entirely; but where the narrowing makes a human's approval mean
something other than what the human is being asked to approve, the narrowing must
be disclosed at the point of approval, in the approval itself.**

Three corollaries:

**(a) Diverting an effect is not suspending its control.** Where the initiator is
an agent and the approver a human outside the initiator set, four-eyes is
*satisfied*, not lifted. DEVELOPMENT-POSTURE-001's ratio - "independence may be
suspended only where there is no party for independence to protect" - is not
engaged by a relief that suspends no independence. A court must not stretch a
precedent to cover a case merely because the same tag enables both.

**(b) The direction of the relaxation decides the fence, not the fact of it.** A
posture that permits MORE to leave the trust boundary needs a fence making it
provably unreachable in production (DEVELOPMENT-POSTURE-001 ratio (b)). A posture
that permits LESS to leave needs the converse fence: that the DIVERSION cannot
persist into production unnoticed. The failure mode is not leakage, it is a
sender who believes a message was delivered when it never left.

**(c) An approval obtained on a false description of its effect is not an
approval.** A human shown "send to <client>" who is in fact authorising "send to
ourselves" has approved a different act. The disclosure is not documentation, it
is the condition of the approval's validity.

---

## reasoning

### What is actually being asked

`channel.send` carries `consequence="high"` (channel_send.py:99, SEC-39), so every
outbound message raises a HITL request, notifies the assignee, and parks. The
Principal's design routes the dev-mode message to a webhook the stack receives,
which the router turns into a work item directed at a named user, surfaced as a
notification, approved in the console.

The advocate's case file argued the independence problem "dissolves" because the
agent initiates and the Principal approves. **That is correct and it is beside the
point.** It was true before this posture existed and will be true after. It
establishes only that no relief from four-eyes is needed - which is a reason this
matter is *narrow*, not a reason it needs no conditions.

### Why the sole-author exemption is not available, and why that does not matter

The Principal's stated motive is that `_sole_active_author`
(hitl_response_auth.py:124) cannot be relied on: it "lapses automatically the
moment a second author exists", and the Classical Visas tenant has more than one.
Verified: the function returns true only for `len(authors) == 1`.

That motive is sound but it argues for nothing in particular. The remedy for
"the bootstrap exemption has lapsed" is that the tenant now has an eligible
independent approver - which is the ordinary state of a working system, not a
problem needing relief. Had the design instead sought to *restore* self-approval,
DEVELOPMENT-POSTURE-001 ratio (a) would refuse it outright: an eligible approver
exists in fact, so suspension would be convenience, not necessity.

The design does not seek that. **Noted with approval.**

### The real hazard, which the case file did not identify

Both parties treated the risk as "does something escape". It does not; that is the
point of the diversion. The hazard is the mirror image, and it is the defect class
the engineering record has spent this entire day clearing:

> A process that is doing nothing must be distinguishable from one that has
> nothing to do.

A diverted send **succeeds**. The verb returns success, the audit row records a
completed egress, the approver sees an approval they granted, and the recipient
receives nothing. Every instrument reports health. This is
`configured-is-not-safe` and `delivery-measured-at-the-destination` in a new
costume, and it would be introduced by the very stack that has been removing it.

Worse, it is *durable*: a dev tag left enabled after a tenant enters service
produces a system that silently swallows every client communication while
reporting each one delivered. The Principal's own instruction - "once we switch
production CV from Tag:Dev to Tag:Not Dev" - concedes the tag will be flipped by
hand, and a hand-flipped flag is one somebody forgets.

### On expiry

DEVELOPMENT-POSTURE-001 made `expires_at` mandatory because "a development posture
with no end is not a posture, it is a permanent condition nobody re-examines". The
advocate may say that reasoning is weaker here, the relief being a narrowing.

The court disagrees, for the reason in the preceding section. A stale independence
suspension is dangerous when someone exploits it. A stale egress diversion is
dangerous **every single time it works as designed**. If anything the case for an
expiry is stronger, not weaker. It is imposed.

### What the court declines to require

The advocate anticipated a condition that the dev path exercise the identical
egress code, lest a defect in real delivery survive untested. The court **does not
impose it**. Requiring the dev path to perform a real send defeats the purpose,
and the honest mitigation is the one the design already has: the loopback is
received by the real intake, so routing, binding, notification and approval are
all genuinely exercised. Only the final transport leg is substituted. That
limitation must be recorded (C5) so nobody later cites dev-mode success as
evidence the transport works - but it is a limitation to disclose, not to cure.

---

## directives

**C1 - The tag must be an affirmative signal.** Following DEVELOPMENT-POSTURE-001
ratio (c): the diversion may run only on a positively declared development signal.
The absence of a production signal must NEVER enable it. A stack with nothing
configured sends normally or refuses; it does not divert.

**C2 - Refuse under any real ingress posture.** The second limb of
`require_codex_trusted_posture`, whose omission was the substance of D2 in the
posture case. Where `oidc_configured or cf_access_configured or
session_auth_configured`, the diversion is unavailable regardless of the tag. A
tenant with real users is in service whatever a flag says.

**C3 - The approval must state the true destination.** The HITL request, the
notification, and the approval surface must each name the loopback as the actual
recipient and name the declared recipient as NOT being messaged. An approver who
would have to read the manifest to discover where the message goes has not been
told. This condition is the ratio; it is not satisfiable by a log line.

**C4 - The delivery record must not claim delivery.** The audit row, the outbox
receipt and any status shown to a user must record `diverted`, never `sent`. No
downstream reader - console, report, or agent - may be able to mistake a diverted
message for a delivered one.

**C5 - Mandatory expiry, and a test that the diversion is unreachable in
production.** `expires_at` is required and an expired tag fails closed to normal
sending. A test must establish that with a production signal present the diversion
cannot run, and it must be red-seeded: the test is only evidence if removing the
fence makes it fail.

**Permission to appeal:** not sought, none granted. Any party may apply.

---

## reserved

The court reserves the question of what `Tag:Not Dev` should default to. The
Principal proposes "any channel they want, starting with their email by default".
Email as a DEFAULT egress for a governed high-consequence verb was not argued and
is not decided here; note only that a default which sends to a real human on first
use deserves its own examination, and that the engineering record carries a
standing instruction against email to this client.
