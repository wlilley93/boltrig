# [2026] VJS-CC-BOLTRIG-DEVELOPMENT-POSTURE-001

**Court:** First Instance (County), repo `boltrig`, jurisdiction `default`
**Convening:** CONVENING-county-2026-07-29-151511
**Submission:** SUBMISSION-2026-07-29-083653
**Question:** May a development-posture tenant dispatch high-consequence verbs without a synchronous human veto, and by what mechanism?

---

## holding

**Option C is ADOPTED IN PRINCIPLE and REFUSED AS SHIPPED. Option E is REFUSED. Options A and D are REFUSED. Option B is expressly not reached.**

A declared development posture is a **lawful mechanism** for suspending the independence limb of four-eyes on a tenant that has no protected party. The kernel work in `881a9df` is, in its architecture, close to right: it lifts independence only, never admits a second relief silently, never lifts the grant check, bounds itself to `control.*`, requires an expiry, admits `superadmin` only, and writes the reliance to both the audit chain and the readable security stream. I do not strike it down.

But **as shipped it is not fenced**, and **as applied to Classical Visas it was unlawful**. Three findings carry that:

1. **The fence is missing its load-bearing limb.** The posture is expressly modelled on `require_codex_trusted_posture` ([2026] VJS-CC-VJS 2). That precedent's fence has **two** limbs: refuse under any production signal, **and** refuse under any real ingress posture (OIDC / CF Access / session login). The second limb is both an express directive (D1) and an express **forbidden item** of that order. The development posture reproduced the first limb and dropped the second. The dropped limb is the one that would have refused Classical Visas, and the one the advocate's own F5 shows would refuse `app.boltrig.io` too.

2. **Its central safety claim is false in operation.** `dev_posture.py` states, and `test_development_posture.py` and the commit record repeat, that the posture "never admits a non-human approver" because `actor_tier` refuses first. `resolve_pat_principal` (`boltrig/identity/tokens.py:145`) hardcodes `actor_tier="human"` on every machine bearer. I ran it: a PAT minted for the declaring superadmin, on a two-author tenant, under a live posture, answered its own `control.adapter.activate` approval and returned `{"status": "answered", "development_posture": True}`. **No human acted.** The posture as shipped delivers Option D - the very option the case file records as "consistently refused" - by accident rather than by design.

3. **The "observed condition the operator cannot assert away" is neither observed nor unassertable, and it fails OPEN.** `production_signal()` (`boltrig/config/environment.py`) reads four process environment variables and returns `None` when all are unset. Unset means permitted. It is a second declaration in a different file, written by the same operator on the same box. The advocate's own disclosure proves it: Classical Visas returns no production signal while serving a real client on a public domain.

I additionally find, **on a point the case file does not plead at all**, that `881a9df` **breached a binding directive**: [2026] VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001 D2 requires the notified set to equal the set the response route admits, derived from one shared definition. `eligible_approval_responders` does not receive the posture. I ran it: under a live posture the notice set is `['client@cv']` and the route set is `['client@cv', 'operator@cv']`. The order's own docstring in that function - "a user it would admit is never missed" - is now false, and the D2 matrix test cannot detect it because it never sets a posture.

**The Classical Visas declaration must be withdrawn now (D1).** **The act already taken under it STANDS (D7)** - it was within grant, fully recorded, corrective, and voiding it would injure the absent party this ruling protects - but it must be put to her.

---

## ratio

**Independence may be suspended only where there is no party for independence to protect, and that absence must be established by a fact the declaring party does not author.**

Four corollaries, each stated to decide future cases:

**(a) Necessity, not convenience, and absence, not declaration.** Every lawful lifting of four-eyes in this repository tracks the *unsatisfiability* of the rule - the founding-owner bootstrap ([2026] VJS-COUNTY 7 D7: invite-only needs a first inviter), the sole-author exemption (`_sole_active_author`: one author, so no independent approver can exist). A posture that tracks the operator's *statement* that protection is unnecessary tracks the wrong fact. Where an eligible approver exists in fact, independence is satisfiable, and its suspension is a convenience, not a necessity.

**(b) A posture-gated relaxation is lawful only under a fence that is mandatory, test-enforced, and makes the relaxation provably unreachable in production - and a court that approves such a fence approves it whole.** Taking the flag and the production signal from an approved wall while leaving behind its isolation limb is not following the precedent; it is citing it. Absent the fence, the relaxation is forbidden.

**(c) A gate whose permissive branch is the absence of a signal is not a gate.** A condition that reads "no production signal" permits by default on every environment nobody configured. A control that must establish a fact must require an affirmative signal of that fact, not the silence of its negation.

**(d) A humanity check is only as strong as the weakest issuer of `actor_tier="human"`.** Where any credential path stamps that tier on a machine bearer, no downstream control may claim to exclude non-human actors. The claim must be made good at the issuer or struck from the record.

And, following the operator-seat court: **"it is the same relief an existing exemption already grants, extended" is an argument for examining the existing exemption, never for opening a comparable one beside it.** That court held that "no worse than the last" makes every future widening self-justifying. `dev_posture.py`'s module docstring makes precisely that argument, in the repository whose court had refused it the day before.

---

## reasoning

### The procedural record, first

The bench was directed to seven file paths. **At the checked-out revision, four of them do not exist.** Local `HEAD` is `e4ceea4`; `main` is *behind origin/main by 6*. `boltrig/config/dev_posture.py`, `tests/security/test_development_posture.py`, the posture limbs of `hitl_response_auth.py` and `hitl_http.py`, and `2026-VJS-CC-BOLTRIG-OPERATOR-SEAT-001.yaml` all live on `origin/main` (`881a9df`, `2640b0c`) and are **not ancestors of HEAD**.

A bench that read only the working tree would have found no posture, no order, and concluded nothing was built. I read everything from `origin/main` and verified `881a9df` is an ancestor of it. I record this because it is a live trap for the next court, and because it means the deployed artefact and the artefact a local reader sees are different things.

### What I verified and where the case file is wrong

**F1 - TRUE, verified.** `dispatch.py:508`: `gated = verb_def.consequence == Consequence.HIGH or verb in self._blocking_verbs`. `control_specs._spec` defaults `consequence: str = "high"`, and `control.adapter.activate` (line 179) takes the default. The veto is the consequence gate. Correctly pleaded.

**F2 - TRUE as far as it goes, and materially incomplete in the way that decides this case.** `approval_response_block` does refuse `actor_tier != "human"` first, before and after `881a9df`. But the advocate's own CORRECTION supplies the fact that destroys the guarantee - `resolve_pat_principal` sets `actor_tier="human"` (`tokens.py:145`) - and pleads it only to establish that a PAT can *reach* the endpoint. The two facts are never connected. Connected, they mean the posture's headline protection does not exist. I proved this by execution, not inference:

```
PAT principal -> actor_tier='human' role='superadmin' subject='operator@cv'
respond_to_hitl -> {'status': 'answered', 'development_posture': True}
```

Two active authors on the tenant, sole-author exemption lapsed, posture live, machine bearer, HIGH control verb, cleared. This is the single most important thing in this judgment and the case file does not contain it.

**F3 - TRUE.** Quoted accurately from [2026] VJS-APPEAL 1's `runtime_summary`. The characterisation "it addresses ADDING a veto, not removing one" is fair and I adopt it.

**F4 - MATERIALLY MISLEADING, and it is the pleading on which Option C rests.** The case file states the wall admits under "(a) a single trusted operator - dev auth, no real ingress - or (b) kernel-attested per-cell uids". That is accurate as a summary. What it never says is that **the design built in reliance on it reproduces neither (a) nor (b).** `posture_block` has no ingress test and no attestation test. It has the flag, the production signal, an expiry, a role check and a verb-prefix check.

I read [2026] VJS-CC-VJS 2 in full. Its D1 reads: *"gate the trusted runtime on dev auth and a dedicated trusted flag and make it fail closed, refuse under any production or staging signal **or any real ingress posture (oidc, cf access, session)**, enforced by test."* Its forbidden list reads: *"running the trusted codex path under any production or staging signal **or with any real ingress posture configured**."*

The ingress limb is not colour. It is a directive and a prohibition. The posture dropped it. And that court's ratio is on all fours against the posture as shipped: *"it is therefore lawful, but ONLY under the mandatory, test-enforced fencing in the directives; **absent any fence it is forbidden**"*, and the sequencing test is that the weaker path be *"provably unreachable in production."* The development posture was not provably unreachable in production. It was reached, in production, on a paying client's tenant, within hours.

**F5 - TRUE, and it is the case file's most honest paragraph.** It concedes that the nearest approved test would REFUSE the candidate tenant. The advocate pleaded it against the option and deserves credit for it. It should have been dispositive at the design stage: if the precedent you are modelling on would refuse your tenant, you have not modelled on it.

**F6 - FALSE, correctly and promptly self-corrected.** The correction is itself verified: `app.py:328-340` tries `looks_like_pat` first and only falls through to the session resolver. The self-correction was properly done.

**F7 - FALSE, and never withdrawn.** F7 reads: *"Classical Visas (two authors, client data) is untouched by this matter."* The SUPERVENING FACT in the same document, twenty lines later, records that **Classical Visas is the tenant that declares the posture and the tenant on which it was relied**. The advocate entered the supervening fact - properly, and I credit that - but left F7 standing. A bench skimming the facts and the options would have ruled on a premise the same document contradicts. F7 must be withdrawn on the record (D8).

**The CORRECTION's narrowing is TRUE and IRRELEVANT.** It says the live question is "only whether the ROUND TRIP itself may be removed", because unattended operation already works headlessly on a *sole-author* tenant. That is correct and needs no ruling. But Classical Visas has **two** active authors; the sole-author route does not run there. The correction narrows the question *away from the only tenant on which anything was actually done*. I decline the narrowing.

**"It refuses under any production signal" - TRUE as code, near-empty as a control.** Verified at source: `production_signal()` checks `BOLTRIG_PRODUCTION`, then `ENV`/`BOLTRIG_ENV`/`APP_ENV` against `{prod, production, staging}`, and returns `None` otherwise. All four are operator-set. Unset permits. The module docstring's "an OBSERVED fact the operator cannot assert away" is **false as shipped**, and the advocate's closing disclosure concedes as much. The honest description is: a second declaration, in a different file, that defaults to permitting.

**"NOT ENABLED ANYWHERE" (commit message) - contradicted by the record within the day.** I do not find it was false when written; I find the record now contradicts it, and that no gate exists to notice the change.

**"It does not reach outside `control.*`, so business verbs and client data are untouched" - true of the posture's scope, false of its one exercised act.** `control.adapter.activate` is specified as *"Activate a reviewed adapter and publish its verb bindings"*. The reliance re-registered the opbox adapter from **99 verbs to 443**. The posture did not permit invoking business verbs without approval; it permitted a decision that **published 344 new invocable bindings over the client's data**, taken by one party, with the client neither asked nor told. "Client data untouched" understates what was decided on her behalf.

**A dangling authority, in the same commit.** `881a9df`'s trailer cites `docs/proposals/DEV-POSTURE-001-draft.yaml`. I searched `origin/main`, the working tree, and all of `git log --all --diff-filter=A`. **It exists nowhere.** This is the third instance of the defect class the operator-seat court named in the paragraph headed ON AUTHORITY HYGIENE ("INV-8 has ZERO occurrences anywhere in boltrig... the same defect class as the C1-C9 incident") - committed one commit-cluster after that order was filed.

**A breached directive nobody pleaded.** Proven by execution against the shipped code:

```
NOTICE  set (eligible_approval_responders): ['client@cv']
ROUTE   set (authorize_approval_response) : ['client@cv', 'operator@cv']
D2 requires these to be EQUAL. Equal? False
DRIFT (admitted but never notified): ['operator@cv']
```

`eligible_approval_responders` calls `approval_response_block` without the `posture=` kwarg, so it computes eligibility against `posture=None` while the route computes it against the live posture. The D2 matrix test `test_notice_set_equals_the_response_route_set` stays green **because it never sets a posture** - a check that cannot fail in the exact dimension the new code introduced. `881a9df` touched that test file only to update the return-type assertions, not to add the row that would have caught this.

**What I verified in the posture's favour, and it is real.** I did not find these overstated:

- The grant check genuinely is applied *after* the relief and is never folded into it (`approval_response_block`), with a test that pins it.
- The two reliefs are genuinely reported separately rather than conflated, and the sole-author branch is tried first.
- The audit row is written **outside** any `try`, so it is durable; only the security-event alarm is best-effort, and the docstring says so honestly.
- The record is genuinely **readable by the client**: `/v1/audit/search` (`platform_routes/observability.py:246`) serves the security stream under `security=1` (line 265, scoped to author/admin), so an `admin`-role client can read `DEVELOPMENT_POSTURE_APPROVAL` events on her own tenant. The claim "a party who was never asked can always read what was done" is, to my verification, true.
- The four-eyes ratchet is **not** weakened by the posture: `assert_author_ratchet` (`config/author_ratchet.py`, called from `control_operations.py:313,327`) fires at execution, independent of the approval path. The operator still cannot demote the client. Operator-seat D2 holds.

### The tenant, and what happens to it

The posture is live on Classical Visas: two active authors, a real client, client data, a public domain, session auth, and no production signal only because an environment variable is unset.

On my ratio it fails four ways: there is a protected party; independence is satisfiable (the notification order found *"the only lawful approver of an operator-raised request is the client"*); the [2026] VJS-CC-VJS 2 ingress limb it claims to mirror would refuse it outright; and the fact it relies on is authored by the party it constrains.

There is worse. The operator-seat court refused a carve-out **on this tenant** on 2026-07-28, and made its refusal revisitable only *"on a record showing D8 satisfied and the client having declined or failed to respond."* **D8 is unperformed** - the order says so in terms (`implementation_status: OPEN`; *"D8 is unperformed"*), and the notification order adds that it *"makes that court's D8 performable; it does not satisfy it and is no record for re-arguing it."*

So on 2026-07-29, the operator obtained by executive act the substance of what a court had refused him the previous day, on the same tenant, while that court's express condition precedent for re-argument remained open. The mechanism differs - in-band rather than host-boundary - and so the operator-seat *forbidden* items are not literally engaged. But the reason the court refused limb 2 was that it *"switches mandatory four-eyes off"*, and that is precisely and only what the posture does.

**Therefore: withdraw the declaration from Classical Visas now (D1).** Not on the expiry of 2026-08-12 - now. On that tenant the posture cannot be repaired by fencing, because Classical Visas will still fail every honest fence.

**The act already taken STANDS.** It was inside the grant (never lifted - verified and tested). It is fully recorded under its own audit verb and on the tamper-evident stream, both readable by the client. It was corrective: it fixed a stale schema behind 42% of that tenant's tool-call failures. And reversing it would deactivate the adapter and re-break the client's service - injuring the very absent party whose interest grounds this ruling. A court does not vindicate an unrepresented party by degrading her service to make a point about her representation. But standing is not ratification: what was decided on her behalf must be **put to her** (D6/D7).

### The Principal, and S-2

The Principal instructed the flag, reaffirmed after the advocate put the objections, and directed the advocate to stop arguing.

[2026] VJS-APPEAL 1 settles the method for this repository and binds me: **construction-to-validity first; ultra vires as a last resort.** *"A Principal directive must be given a lawful construction where its words fairly bear one before any part is declared ultra vires."* I apply it.

**The instruction is NOT ultra vires.** The Principal's stated requirement, recorded verbatim in `881a9df`, is: *"on a tenant not yet in service, work without a second human answering each approval, and turn it off again after."* That construction is entirely lawful. It is Option C properly fenced. It conflicts with nothing. **I find the instruction honoured on its conforming construction, and I decline to characterise any part of it as ultra vires.**

**What was ultra vires was the application, and it was the executive's, not the Sovereign's.** Classical Visas *is* in service. The Principal's own words - "not yet in service" - do not reach it. The act that conflicted with binding precedent was not the instruction to build; it was the decision to **declare the posture on a tenant the instruction's own premise excludes**, while the operator-seat refusal stood and its D8 condition was open. That decision belonged to the executive office, and on it I find plainly against.

**Was legislation the lawful route?** For the mechanism, **no**. A bounded calibration inside the existing manifest-and-eligibility seam needed a court, not a statute, and the advocate correctly convened one. For the Classical Visas application, **yes - or D8.** Where a court has refused relief on a tenant and fixed an express condition for re-argument, the lawful routes are exactly two: satisfy the condition, or amend the enacted floor by due process as Sovereign. Neither was taken. The route actually taken - build it, deploy it, rely on it, then file - inverts the order the whole system depends on. That it was filed candidly is genuine mitigation, and I weigh it. It is not a cure.

**A word on the direction to stop arguing.** Under SPEC-LAW S-3 the advocate is advocate, advisor and engineer, and under S-2 an executive demand that conflicts with binding precedent is to be met with the lawful route offered, never silent compliance. The advocate did put the objections, did build as directed, and did then file the matter with the supervening fact and an adverse disclosure entered against his own work, and withheld his preference. That is the duty substantially discharged under pressure. The residual failure is narrower and I state it precisely: **the thing was deployed to a client tenant and relied upon before the court sat.** Under S-4..S-8 that falls below reasonable skill and care. The remedy is to make the work good - D1 through D8 - and nothing else. No blame attaches, and none is intended.

### The absent third party

The client on Classical Visas is not represented here, was not asked, and did not consent.

The operator-seat court treated non-representation as decisive against the demotion limb, because that limb *"asks the protected party to sign away their own protection."* The obvious argument is that this posture is better: it does not coerce her signature.

**I reject that, and it is the wrong comparison.** The demotion limb's vice was *consent extracted*. This posture's vice is *consent dispensed with*. A court cannot hold that not asking the protected party is an improvement on asking her badly. Both remove her protection; one at least leaves a trace of her in the record. Her non-representation carries **the same weight it carried on 28 July, and here it lands harder**, because on this record something was actually done: the invocable surface over her data went from 99 verbs to 443, decided by one party who was also the only party asked.

But - and this is why I adopt Option C rather than Option A - **her absence is not decisive against the mechanism.** It is decisive against the mechanism *on her tenant*. On a tenant with no client there is no absent party at all, and independence is protecting nobody. That is exactly why the condition must be **the demonstrable absence of a protected party**, not the operator's declaration that protection is unnecessary. Fix the condition and the objection dissolves, because the objection *is* the condition.

### The strongest argument against my own conclusion, and why it does not carry

The strongest case against me is not Option E. It is this:

> *You have refused the posture as shipped for want of an ingress limb, while conceding the record proves nothing was actually at risk. The grant check was never lifted. The ratchet still holds - the operator cannot demote the client. Non-human approvers are refused at the front of the function. The scope is `control.*`. Everything is recorded, and recorded where the client can read it. The one act taken was corrective and fixed 42% of her failing tool calls. Meanwhile the advocate's correction proves the operator could already have done all of this headlessly on a sole-author tenant with no ruling at all, and on any tenant could have obtained the identical outcome via `boltrig initiate` at the host boundary or a second operator seat. You are refusing a mechanism that adds a rich audit record to conduct that was already available without one. Refusal does not protect the client; it just moves the same act somewhere less visible. [2026] VJS-CC-VJS 2 itself says prove the weaker path first and then harden - so harden this one, do not refuse it.*

That argument has real force, and two of its limbs I accept outright: the recording is genuine, and the act was corrective.

It does not carry, for three reasons.

**First, its central factual premise is false, and I proved it false.** "Non-human approvers are refused at the front of the function" is the load-bearing claim, and `resolve_pat_principal` defeats it. A machine bearer *is* an admitted approver under this posture. So the argument's own account of what is at risk is wrong: what shipped is not "four-eyes minus one click with a rich record" but "a control that normally requires two humans, satisfiable end to end by a token, on a live client tenant." Once that is on the table, the "nothing was really at risk" framing collapses. Nothing *happened* to be at risk on the one act taken. That is a fact about what was invoked, not about what was permitted, and a court that reasons from the former licenses the latter.

**Second, "he could have done it anyway" is the argument the operator-seat court expressly forbade.** Its forbidden list names *"justifying a new boundary carve-out on the ground that an existing boundary command already confers more - that is an argument for CLOSING the existing command."* The point is general and it binds: that another route already permits X is a reason to examine that route, never to open a second one beside it. Otherwise every widening is self-justifying by reference to the last, which is exactly what that court said it would not have.

**Third, [2026] VJS-CC-VJS 2 does not say "prove it weak, then harden." It says lawful *only under mandatory, test-enforced fencing*, and *"absent any fence it is forbidden."*** The sequencing licence is conditioned on the weaker path being **"provably unreachable in production."** This one was reachable in production and was reached there on day one. The precedent the argument invokes is the precedent that refuses it.

And there is a fourth answer the argument cannot meet at all: it says nothing about the D2 breach. `881a9df` silently broke the equality a court had ordered eight days earlier, in the same function whose docstring cites that order, and the test that owns the directive could not see it. Whatever else is true, that is not a mechanism that has been proven safe. It is one whose one binding constraint was broken on arrival and went unnoticed by everybody, including the advocate who filed this case.

I have taken the argument at its strongest. It fails.

---

## directives

**D1 - Withdraw the posture from Classical Visas now.** Not on its 2026-08-12 expiry. Classical Visas has a client, client data, a public domain, session ingress and an eligible untried approver; it fails every fence in D2-D5 and cannot be brought within them.

**D2 - Restore the fence limb the precedent requires: refuse under any real ingress posture.** `posture_block` must refuse when `Settings.oidc_configured or cf_access_configured or session_auth_configured`, exactly as `require_codex_trusted_posture` does under [2026] VJS-CC-VJS 2 D1.

**D3 - The posture must lapse automatically when a party it could harm appears.** Mirroring `_sole_active_author`: the declaration must enumerate the active author-tier identities it covers, and `posture_block` must refuse when any active user whose role is in `AUTHOR_ROLES` is not enumerated.

**D4 - Make the humanity claim good at the issuer, or strike it from the record.** Either `resolve_pat_principal` must yield a principal the posture path refuses, or every statement that the posture "never admits a non-human approver" must be removed.

**D5 - The environment condition must fail closed.** Require an **affirmative** non-production signal instead of the absence of a production one.

**D6 - Repair the notice/authority drift, and make the D2 matrix able to see it.** `eligible_approval_responders` must receive and pass `posture`, so the notified set is again derived from one definition.

**D7 - The act stands; put it to the party it was taken from.** The client must be told that a control approval was cleared with no independent reviewer, and that the invocable surface over her data went from 99 verbs to 443.

**D8 - Correct the record: F7 and the dangling citation.** Withdraw F7 from the submission, and either add `docs/proposals/DEV-POSTURE-001-draft.yaml` or record its absence. The forward-looking half is a gate asserting every path referenced in a `Refs:` trailer resolves in-tree.

**Sequencing.** D1 is immediate and unconditional. D2-D6 are conditions precedent to declaring the posture on **any** tenant. D7 and D8 are record-repair and run in parallel.

---

## reserved

I expressly do **not** decide:

- **Option B** - downward calibration of `consequence` / `blocking_verbs` as manifest data. Nothing was built on it and no tenant relies on it.
- **Option D on its merits.** I hold only that the shipped posture must not deliver a non-human approver *by accident*.
- **Whether the seat-operator question may return.** Governed by the operator-seat court's own D8 and exception clause.
- **Whether `admin` is the right role for a client to hold**, or whether the client should hold `{all: true}` scope.
- **The `AUTHOR_ROLES` double duty**, reserved twice already.
- **The two divergent histories.** A delivery-hygiene matter, recorded because the next bench will hit it.
- **Anything about `app.boltrig.io`.** F5 makes it a candidate; nothing was declared on it. D2 would refuse it on today's configuration.

---

**Disposition:** Option C adopted in principle, refused as shipped. Option E refused. Options A and D refused. Option B not reached. The Classical Visas declaration is withdrawn forthwith (D1). No tenant may declare the posture until D2-D6 are discharged. The act taken under it stands, and must be put to the client (D7). The record is to be corrected (D8).

*Given at First Instance, 2026-07-29.*
