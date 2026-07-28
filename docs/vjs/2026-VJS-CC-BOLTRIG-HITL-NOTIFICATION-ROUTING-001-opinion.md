# [2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001 - opinion

First Instance, single judge, boltrig County. Case file: SUBMISSION-2026-07-28-184536.
Convening: CONVENING-county-2026-07-28-184547, case file
`sha256:80f5b43f90034622ba0e2a25069e28dcfbe35b5935440c7ad7291e27ed0ba1d0`.

**No citation is minted**, for the reason recorded in the schema-validation ledger order: the
allocator refuses the canon COUNTY series at a subscriber seat ([2026] VJS-PC 19) and minting at
canon offers a number this repository's mirror already uses.

**Implementation status: OPEN.**

---

## 1. Findings on the facts

Every file the pleading cites was opened and the cited lines checked. The live-tenant data on
Classical Visas is accepted on the scrutiny-verified record of the operator-seat matter of
earlier today (SUBMISSION-2026-07-28-151116, SELECT-only verification, this court's own
occasion); the cv deployment is not reachable from this seat at the time of writing, and every
proposition about the CODE below is verified by me line-by-line.

**F1 - CONFIRMED as to routing; OVERSTATED as to delivery.** `hitl.py:244` is exactly
`subject = req.assignee or req.requested_on_behalf_of or req.requested_by`, and
`_notify_request` (`:235-252`) enqueues to that ONE user. An operator-raised approval with no
assignee addresses its raiser. **Corrected:** "notifies its raiser" overstates what happens on
the live tenant. `enqueue_user_notification` matches only enabled `notification_prefs` rows for
the event (`channel_notify.py:81-84`) and returns `[]` when none match; the pleading's own F4
records that Classical Visas has ZERO pref rows. On the live tenant the notice therefore reaches
NOBODY - not the approver, and not even the raiser. The routing defect is exactly as pleaded
(the subject set excludes the only lawful approver by construction); the delivery posture is
worse than pleaded.

**F2 - CONFIRMED, with one boundary noted.** `authorize_approval_response`
(`hitl_response_auth.py:142-178`) admits a human outside the initiator set
(`:158-170`), matching the assignee if set (`:156-157`), holding the live grant for the verb
(`:171-177`). The sole-author exemption (`:124-139`) lifts independence only while exactly one
active author-tier user exists. Within HITL response eligibility `AUTHOR_ROLES` enters only
through that exemption (`:132`, `:137`), as pleaded; its other use is `can_author`
(`rbac.py:265`) - the double duty the operator-seat court expressly reserved and this court
does not disturb.

**F3 - CONFIRMED on the record, with one qualification.** The operator-seat record (same day,
scrutiny-verified to the second) establishes two active author-tier users on Classical Visas
(the operator, `superadmin`; the client `info@classicalvisas.com`, promoted `member` -> `admin`
at 08:30:31 by the last act performed under the exemption), so `_sole_active_author` returns
False for everyone and the exemption has lapsed. **Qualification:** eligibility is grant-based
(F2), so "the ONLY lawful approver is the client" holds for verbs within the client's live
grant. The operator-seat court walked every gate for `control.invitation.create` and found the
client eligible; with the tenant's `["*"]` permissions and the client's `admin` role the
practical effect is as pleaded.

**F4 - CONFIRMED, and strengthened.** The operator-seat D8's words "actually PUT TO
info@classicalvisas.com on a window of at least 24 hours" are quoted exactly. The shipped code
cannot perform it: by F1 the notice never addresses the client, and by F1-as-corrected it
addresses nobody at all on that tenant. The manifest knobs are deader than pleaded:
`primary_channel` and `notify_via` appear ONLY at `manifest.py:175-176` (dataclass defaults) and
`:590-591` (parse) - a full-repo search finds no reader anywhere. The scrutiny clerk's finding,
that D8's check can go green on a request that expires unheard, is the defect this order's
directives are drafted against.

**F5 - CONFIRMED exactly.** `_approval_visible` (`hitl_response_auth.py:83-99`) admits a
non-initiator human holding the verb grant to collection endpoints. Visibility is not the
defect; the approach is. `_notify_request` swallows every fault (`hitl.py:251-252`, P9) and
`enqueue_user_notification` returns `[]` on no match (`channel_notify.py:83-84`).

**Correction to the convening brief:** the case file pleads F1-F5; the brief's "F1-F6" is a
slip. There are five pleaded facts.

---

## 2. Precedent

**BINDING: [2026] VJS-APPEAL 1 (2026-VJS-CA-BOLTRIG-CODEX-APPROVAL-ROUTING-001), read in
full.** HIGH/blocking verbs hit the durable kernel HITL; the kernel's HITL record is the
governance act, and human control is calibrated by data (consequence, blocking_verbs), never
bolted on beside it. What this order touches is the side channel that ADVERTISES that record.
It adds no veto, removes none, and recalibrates nothing; the recorded request remains the truth
exactly as the Appeal's affirmance presupposes.

**THE OCCASION, treated as constraint: the First Instance operator-seat ruling of 2026-07-28**
(SUBMISSION-2026-07-28-151116, court record at
`Jellytot/docs/court-2026-07-28/first-instance-three-matters.json`), read in full together with
the scrutiny clerk's review. Three things bind this bench's drafting, though not its question:
its D8 (the invitation "actually PUT TO" the client) is the occasion of this case; its reserved
questions (the `AUTHOR_ROLES` double duty; `seat-operator` re-arguable only on a record showing
D8 GENUINELY satisfied) are live constraints on what may be decided here; and the scrutiny
clerk's finding - that D8 orders an act the shipped notifier cannot perform, with a check that
can go green without the act - is verified above (F1, F4) and is precisely the defect class this
order's checkable clauses must not repeat.

**NOT RELIED ON for any substantive point:** the remaining authorities listed by `vjs route`
(COUNTY 1 chat-authority, COUNTY 3 chat-attachments, COUNTY 4 chat-regenerate, COUNTY 9
audit-depth) were not needed to decide this question and are not cited. No authority was relied
on that was not read.

---

## 3. Reasoning

The question is whether the approval notification should be brought to the eligible
approver(s), and by which route. All four pleaded options are weighed.

**Option B - REFUSED.** Leave routing; rely on pull and visibility. F5 is confirmed: visibility
already admits the eligible approver to the collection endpoints, and pull is already possible.
It has never once been exercised: on the verified record, 17 HITL requests on the tenant, every
response row from the operator, and the one posture that matters - an approver who does not
know a request exists - is exactly the posture pull cannot cure. A queue never heard of is not a
route "put to" anyone; B leaves the operator-seat D8 unperformable by design. The
smallest-change argument is real and insufficient: the change it saves is small, and so is what
it buys.

**Option C - REFUSED.** Notify all active author-tier users. Three independent grounds. First,
it is wrong on eligibility: author tier is not the responder set (F2) - it notifies users who
lack the verb's live grant and, worse, on a single-author tenant it notifies ONLY the initiator,
reproducing the exact defect where the exemption serves. Second, it is wrong on authority:
routing a governance notice by `AUTHOR_ROLES` would build fresh load onto the double duty the
operator-seat court expressly reserved (`AUTHOR_ROLES` as both studio authority and four-eyes
count), entrenching the conflation before that question is decided. Third, its one virtue -
cheap determinism - is bought by computing a set that is not the set the law of the response
route admits.

**Option D - REFUSED as a general rule; its existing kernel is kept.** Requiring the raiser to
name an assignee asks the raiser to compute, at raise time and by hand, the eligibility set the
kernel already computes at response time - and to compute it under uncertainty about grants,
lapses and seats. A wrong answer is not neutral: a stale or ineligible assignee REFUSES every
other responder (`hitl_response_auth.py:156-157`), converting a routing inconvenience into an
authorization deadlock - strictly worse than no notice. Where an assignee IS set, the present
routing already addresses them first (F1); that behaviour is sound and this order leaves it
untouched.

**Option A - ADOPTED, on the following ratio.** Extend `_notify_request` to also enqueue to
every user who could lawfully respond, deduplicated against the present subject, fail-safe as
now. Both pleaded costs are real and both are answered. The grant sweep is a bounded read over
one tenant's users at the moment a high-consequence verb pends - the rarest write path the
kernel has, and cheap beside the gate it advertises. The silent gap (a recipient with no
prefs/bindings hears nothing) is confirmed on the live tenant (F1-as-corrected) and is a
DELIVERY-DATA gap, not a routing defect: the kernel cannot invent a bound surface, and SEC-179
rightly forbids it from guessing one. It is cured by data (D4 below), and pull-visibility (F5)
stands as backstop meanwhile.

> **THE RATIO.** Notice follows eligibility. The side channel that advertises a governance
> record must address the same set the authorization rule would admit, derived from ONE shared
> definition, so that notice and authority cannot drift apart: a system that admits X to answer
> and notifies only Y has built its deadlock into its routing table. Notification widens the
> AUDIENCE, never the AUTHORITY - being notified confers no power to approve, and the response
> route re-checks everything at answer time. The recorded request remains the truth (SEC-179,
> P9); delivery remains best-effort and fail-safe; a notifier fault never voids anything.

**Corollary 1, on checks.** A check of this cure must test the OPERATIVE artefact. A test of
code constants is evadable wherever a deployed manifest or tenant data overrides them - the
exact defect the scrutiny clerk found in the operator-seat D5. The routing tests bind the
kernel behaviour; the tenant discharge binds the tenant database.

**Corollary 2, on "put to".** A request that expires unheard is not a request that was put to
anyone. Expiry proves silence, not refusal; any order (including the operator-seat D8) whose
satisfaction could be read from a timed-out row alone is satisfiable by doing nothing, and a
reserved question keyed on such a record would be re-argued on a record that proves only that a
row expired.

**Corollary 3, on shared definitions.** Where one rule admits and another addresses, the two
WILL drift - the pleading's strongest point for A, and this court makes it a condition: the
notice set must be derived from the same eligibility rule the response route enforces, not a
parallel computation that happens to agree today.

---

## 4. Disposition

Option A **adopted**. Options B, C and D **refused**, each on stated grounds; D's existing
assignee-first routing is kept. The defect fix directed is the one named in the convening:
extend `_notify_request` so a HITL request is ALSO enqueued via the existing
`enqueue_user_notification` to the eligible-approver set - users who may lawfully respond per
`hitl_response_auth.py` (not in the initiator set, human, assignee-consistent, holding the
verb's live grant, the sole-author exemption applied exactly as the response route applies it) -
deduplicated against the current subject, best-effort and fail-safe as now, with tests seeded
red. No different or additional cure is adopted; the delivery-data gap on the live tenant is
not a kernel cure and is ordered as data under D4.

**Reserved, not decided.** The `AUTHOR_ROLES` double duty remains reserved where the
operator-seat court left it; Option C is refused partly so that this order does not entrench
the conflation ahead of that question. The `seat-operator` question is untouched: this order
makes the operator-seat D8 performable; it does not satisfy it, and nothing here is a record on
which that question may be re-argued.

---

## 5. Limits, recorded rather than ordered

**L1.** On a tenant with no delivery data - no prefs, no bindings, no socket channel - the
extended notice still enqueues nothing (`channel_notify.py:83-84`). That is an honest gap, not
an error; the kernel's part is to address the right set, the tenant's part is to be reachable.
D4 binds the live tenant's part.

**L2.** This order does not make any particular approval happen, and does not train anyone to
approve. It removes a routing table that made the lawful approver's silence structural. What
the client does with a notice actually received is hers.

**L3.** The notice set is computed at raise time from the users and grants then standing. A
user who becomes eligible while a request pends is not retroactively notified; pull-visibility
(F5) is the answer for the window between, and it is sufficient because visibility was never
the defect.

---

## 6. Obiter

**O1.** The same defect has now appeared twice in one day in two costumes: a ruling that
ordered an act the shipped code could not perform, and a pleading that described a notice as
"reaching its raiser" on a tenant where it reaches nobody. In both, the prose described the
intent of the mechanism rather than its measured behaviour. The discipline that catches it is
the one the operator-seat D9 analogue states: the test is run against the artefact that
operates, and it is run red first.

**O2.** `notify_via` and `primary_channel` are parsed configuration with no reader (F4). A
manifest knob nothing reads is a promise the system makes to every operator who edits it. This
order does not direct their repair - no option pleaded it and the question is not before the
court - but a future case file on dead notification configuration would find the measurement
already taken.
