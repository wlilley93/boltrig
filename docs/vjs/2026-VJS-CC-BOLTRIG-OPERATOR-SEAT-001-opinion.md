# [2026] VJS-CC-BOLTRIG-OPERATOR-SEAT-001 - opinion

First Instance, 2026-07-28. Matter `operator-seat`, submission `SUBMISSION-2026-07-28-151116`.

Disposal: **refused**.

> This document is the court's own text, transcribed verbatim from the convening record
> at `~/Projects/Jellytot/docs/court-2026-07-28/first-instance-three-matters.json`.
> Nothing here is paraphrased, and no condition has been added to what the court wrote.
> It was filed on 2026-07-29, a day after it was given: the ruling had lived only in that
> JSON, so the citator could not see it and every touch of this area was being routed to a
> fresh court that would have re-decided a question already decided.

## Holding

Both limbs are refused: `seat-operator` is refused because the bootstrap necessity that alone justifies a host-boundary carve-out is not made out (an eligible approver exists and the in-band route has never once been exercised), and demoting the client is refused because it does not correct the role, it switches mandatory four-eyes off and asks the protected party to sign away their own protection.

## Ratio

A host-boundary carve-out from an in-band control is justified only by bootstrap NECESSITY - that no in-band route can discharge the act - and necessity is measured on the record, not on the record's awkwardness. Where an eligible approver exists in fact and the in-band route has never been exercised, the boundary stays shut and the defect is repaired in-band. That another boundary command already confers more is an argument for closing that command, never for opening a comparable one beside it, because "no worse than the last" makes every future widening self-justifying. Correlatively, the four-eyes ratchet is ONE-WAY: no control verb may reduce a tenant's active author-tier count from two to one, because that silently converts a mandatory independent approval into an optional one; and such a reduction may never be effected by asking the protected party to approve the removal of their own protection.

### Ratio note

Refused on both limbs; restorative directives D1-D8; Option 4 reserved.

## Reasoning

# Judgment

## 1. What I verified, and where the case file is wrong

I read the pleaded code sites and queried the live Classical Visas database (SELECT only). The mechanism the case file pleads is **exactly right**, and the live record proves it more precisely than the pleading does:

- 08:19:12 `control.invitation.create` raised with `{"role": "member"}`
- 08:26:18 self-approved under the exemption (lawful: the operator was then the sole author)
- 08:27:05 user `info@classicalvisas.com` created, `source=invitation`, role `member`
- 08:29:31 `control.user.update` raised with `{"role": "admin"}`
- 08:30:05 self-approved under the exemption (still lawful: the client was still `member`)
- 08:30:31 executed - the client becomes author-tier - **the exemption dies**

"The last act performed under the exemption destroyed it, unannounced" is literally and exactly true. `AUTHOR_ROLES` (rbac.py:163) contains both `superadmin` and `admin`; both CV users are `active`; `_sole_active_author` (hitl_response_auth.py:124-139) therefore returns False for everyone. I also confirm `_spec` defaults `consequence="high"` (control_specs.py:38) and neither verb overrides it; `dispatch.py:502` gates on exactly that; `initiate.py:86-95` returns 3 (and on CV is doubly barred, since both a `superadmin` and an `admin` are in `_OWNER_TIERS`); and `mint-token`/`set-password` refuse absent users.

But three findings are material and change the outcome.

**(A) The central necessity claim is false.** The case file says "**Every** route to a second operator requires an approval that requires a second operator." Two sentences earlier it concedes "the only lawful approver of an operator-raised request is **the client**." Those cannot both be true, and the second is wrong. I walked every gate the client must pass to approve `control.invitation.create`:

- `authorize_hitl_scope` -> `departments_for("admin", {all:true})` returns `None` (rbac.py:315-316) -> `_scope_matches` returns True at :60-61
- `actor_tier == "human"` - satisfied
- `request_fingerprint` present - `has_fp = t` on every live row
- `assignee` is **NULL on every live HITL row**, so the assignee gate at :156-157 never fires
- initiators `{will.lilley93@gmail.com}` INTERSECT respondents `{info@classicalvisas.com}` = empty -> no 403, no exemption needed
- `grants.check` -> client scope `{all:true}` -> `grants_for_scope` -> `allow=["*"]`; live `tenant_permissions` = `allow ["*"], deny []` -> passes

There is no author-tier gate anywhere on the respond path (`app.py:591-600` -> `respond_to_hitl` -> `authorize_approval_response`). **The route to a second operator is open today, with no code change.** It has never been used: `hitl_responses` holds 9 rows, all `will.lilley93@gmail.com`, **zero** from the client. The two `control.invitation.create` requests on 2026-07-26 were left to expire. This is not a deadlock. It is an unexercised route.

**(B) `AUTHOR_ROLES` is not "used ONLY by the exemption".** It is also read by `rbac.can_author()` (rbac.py:263-265), invoked at `config/control_channel_ops.py:30`, `kernel/platform_routes/_shared.py:20,37` (feeding `observability.py` x4 and `admin.py` x4), `kernel/channel_routes.py:423,591`, `kernel/channel_gateway_routes.py:65`, and `config/control_approval.py:59`. A second, differently-populated `AUTHOR_ROLES` in `ui/src/deck/deckMap.ts:17-23` gates the Agents/Automations rows and Studio/Dev-console columns. The *load-bearing half* of the claim is nonetheless correct and I verified it independently: approver eligibility genuinely does not require author tier, because grants come from SCOPE, never role (`grants_for_scope`, rbac.py:91-127; the `_coherent_scope` docstring at provisioning.py:115-128 says so in terms).

**(C) The "narrower cure" is the most destructive option on the list.** Demote the client to `member` and `_sole_active_author` finds exactly one active author - the operator - and returns True. **The self-approval exemption revives.** Four-eyes stops being mandatory on CV. And because `control.user.update` is high-consequence, the demotion must itself be approved by the client: the operator would be asking the client to approve stripping their own author tier and, with it, the mandatory independent approval that protects them. That is the single worst thing to put in front of a client, and the case file discloses none of it. Option 1 is not the conservative choice; it reaches the same "one human has root" endpoint the AGAINST section fears, needs no host access at all, and carries the absent party's signature.

**On authority hygiene:** Option 2 proposes "an INV-8-class audit row". **INV-8 does not exist anywhere in boltrig** - zero occurrences outside the submission itself. It is an *opbox* kernel invariant living in the VJS repo. I have not adopted a condition under that name. My audit directives are written against the mechanisms I read: `AuditWriter.write`/`AuditEvent` (kernel/audit.py:257) and `SecurityEventWriter.write`/`SecurityEvent` (kernel/security_events.py:82). This is the same defect class as the C1-C9 incident, and I flag it rather than repeat it.

## 2. The law

**[2026] VJS-COUNTY 7** (`2026-VJS-CC-BOLTRIG-FIRST-PARTY-AUTH-001.yaml`, binding), read in full, is directly on point. D7: "seed_the_founding_owner_via_a_boltrig_initiate_bootstrap_and_keep_the_whole_flow_invite_only_no_open_self_signup." The holding gives the reason: "The founding OWNER is seeded out-of-band by a `boltrig initiate` bootstrap, **because invite-only needs a first inviter**."

The host boundary was opened **once**, and the stated ground was a necessity no in-band route could discharge - with zero users there is nobody to invite you. The carve-out is singular and reasoned, and its reasoning is bootstrap-necessity. The very reasoning that justified `initiate` refuses a second carve-out where the in-band route is open. Here it is open, and untried.

A `seat-operator` command would not breach COUNTY 7's `forbidden` limb against "open self-signup" - a host-shell command is not open. It fails on D7's positive limb instead: the boundary is opened exactly as far as the bootstrap requires and no further.

## 3. The strongest argument against refusing, and why it does not carry

The strongest point against me is one the case file understates. **The boundary already confers strictly more, by a worse route.** `set-password` (initiate.py:180-224) and `mint-token` (mint_token.py:60-77) each operate on *any existing user with no role restriction*. `mint-token` caps the PAT at the user's own grants - the client holds `["*"]`. `user_totp` on CV is **empty**, so COUNTY 10's second factor does not stand in the way. Worse: `set-password` writes its audit row with `actor=email`, the **target** user, so a host holder resetting the client's password produces a row that reads as the client's own act.

So a host holder can today mint a `*`-scoped PAT as `info@classicalvisas.com`, approve the operator's own request wearing the client's identity, and leave a trail attributing it to the client. On that footing, refusing `seat-operator` protects nothing and arguably pushes the operator toward the impersonation route, which is strictly more damaging because it *forges* the client's participation in four-eyes instead of adding a real second human. The honest response, the argument runs, is to allow the command on conditions so the capability at least becomes attributable.

It does not carry the day, for three reasons.

**First, it proves too much.** "The boundary already allows something worse" is an argument for closing the worse thing, not for opening a comparable one beside it. The correct answer to discovering that `set-password`/`mint-token` silently impersonate the client is D6 - attribute them and alarm them - not a third boundary command justified by the leakiness of the first two. Accepted as pleaded, it makes every future widening self-justifying: each new one is always "no worse than the last".

**Second, the necessity is simply absent.** COUNTY 7 opened the boundary for an impossibility. Here there is an inviter, an eligible approver, an active account that has logged in, and a live route with a verified-open path. The three timed-out requests are evidence of a 3600-second window (`manifest.py:177` and `:592`), not of a legal impossibility. A carve-out cannot rest on a deadlock the record shows was never tested.

**Third, `seat-operator` does not reduce the impersonation risk at all - it leaves it exactly where it is.** It adds an attributable route and removes nothing. Only D6 reduces it, and D6 needs no authority-creating command. If the concern is genuine, the remedy is D6.

## 4. The floor

The client is a real third party. Their four-eyes protection is a protection *of them*, and they are not represented in this case file. I will not strip a protection from an absent party on an operator-side application, still less by a route whose execution requires their signature on its own removal. That consideration is decisive against limb 2 independently of everything above.

## 5. Relief

Refusing both limbs while leaving the live problem standing would be an empty ruling, and the duty is to make the work good. The record discloses real defects, and D1-D8 direct their repair: the exemption can destroy itself silently (D3), nothing warns that the approval you are giving will end it (D4), the one-hour window is the actual proximate cause of what was experienced as deadlock (D5), the boundary commands misattribute and do not alarm (D6), the two `AUTHOR_ROLES` sets have drifted (D7), and the open route must actually be put to the client before this question returns (D8).

## Directives

### D1 (binding: True)

REFUSED (limb 1). No new host-boundary CLI command that creates a user identity. The identity command set remains exactly {initiate, set-password, mint-token}. Checkable: a test asserts the guard tuple at boltrig/api/cli.py:200 and the registered subparser names in _add_identity_parsers are exactly that three-element set, and FAILS when a fourth is added; plus a test asserting boltrig/api/initiate.py remains the only host-boundary call site constructing a User(...) object.

### D2 (binding: True)

REFUSED (limb 2), and the four-eyes ratchet is made one-way. Any control verb (control.user.update, control.user.deactivate, or any other) MUST refuse when its effect would reduce a tenant's count of active users whose role is in AUTHOR_ROLES from >=2 to exactly 1. Checkable: seeded test - tenant with an active superadmin and an active admin; control.user.update demoting the admin to 'member' raises, and _sole_active_author still returns False for the superadmin afterwards. A second seeded test asserts the refusal does NOT fire on a 3->2 or 2->2 transition.

### D3 (binding: True)

Announce the crossing. Any control verb whose execution changes a tenant's active author-tier count across the 1<->2 boundary MUST write an AuditEvent via AuditWriter.write (kernel/audit.py:257) naming the verb, the count before, and the count after. Checkable: seeded test - promote a one-author tenant's sole member to 'admin'; assert exactly one such row with before=1 and after=2; assert NO such row is written for a promotion that leaves the count unchanged.

### D4 (binding: True)

Warn when the exemption is spent to end itself. Where authorize_approval_response applies the sole-author exemption to a request whose verb and params would raise the active author count above 1 (control.user.update or control.invitation.create carrying a role in AUTHOR_ROLES), respond_to_hitl MUST return a distinct flag alongside the existing sole_author_exemption key and record it in the detail of the hitl.sole_author_approval audit row (hitl_http.py:114-131). Checkable: seeded test asserts the flag is present for a control.user.update promoting a member to admin, and absent for an exempted approval of any verb that does not change the author count.

### D5 (binding: True)

Fix the window that caused this. The shipped approval timeout for control.* verbs must be at least 86400 seconds. Checkable: a test reads the value actually compiled into boltrig/config/manifest.py at BOTH :177 (the dataclass default) and :592 (the raw.get fallback) and FAILS if either is below 86400 or if the two disagree with each other. The test must assert the shipped constant, not a value it supplies itself.

### D6 (binding: True)

Attribute the host boundary honestly and put it on the security stream. set-password (initiate.py:214-222) and mint-token (mint_token.py:77-84) MUST NOT write an AuditEvent whose actor is the TARGET user; the row must name the host boundary as actor. Each must additionally write a SecurityEvent via SecurityEventWriter.write (kernel/security_events.py:82) under a new SecurityEventType member - additive to the four in models/audit.py:33-36, consistent with [2026] VJS-COUNTY 9 D3. Checkable: seeded test runs set-password for user X and asserts (a) no audit row for that act has actor == X, and (b) exactly one SecurityEvent row is written.

### D7 (binding: True)

Reconcile the two AUTHOR_ROLES sets, which currently disagree. boltrig/identity/rbac.py:163 contains superadmin and admin; ui/src/deck/deckMap.ts:17-23 does not. Checkable: a test asserts the TypeScript set equals the Python set element-for-element (or that the TypeScript set is generated from the Python one) and FAILS on any divergence in either direction.

### D8 (binding: True)

Exercise the open route before this question returns. A control.invitation.create for a second operator-side human must be raised and actually PUT TO info@classicalvisas.com on a window of at least 24 hours (per D5). Checkable by SELECT on the tenant database: either a hitl_responses row with respondent='info@classicalvisas.com' for that request, or a hitl_requests row with verb='control.invitation.create', (timeout_at - created_at) >= 24 hours, and status='timed_out'. Neither condition is presently satisfied: hitl_responses holds 9 rows, all from the operator.

## Reserved

Option 4 - a distinct `operator` tier that satisfies four-eyes without being author-tier - is expressly RESERVED, not refused. The case file is right that `AUTHOR_ROLES` is doing double duty: "may use the authoring studios and admin console" and "counts as an independent author for four-eyes" are different questions wearing one name, and that conflation is what let a client-facing role grant silently redefine an operator-side control. That is a real design defect worth deciding.

I should not decide it on this record. To decide it I would need: (a) an enumeration of what `info@classicalvisas.com` actually needs to do, as against what role `admin` currently confers; (b) the effect of a new tier at each of the six verified `can_author` call sites (config/control_channel_ops.py:30, kernel/platform_routes/_shared.py:20 and :37, kernel/channel_routes.py:423 and :591, kernel/channel_gateway_routes.py:65, config/control_approval.py:59); and (c) how it composes with the workspace-role ceilings in rbac.py. None of that is before me.

Also expressly reserved: whether a host-boundary `seat-operator` could ever be justified. I refuse it on THIS record because the necessity is absent. It would become arguable on a record showing D8 satisfied - the invitation genuinely put to the client on a 24-hour window - and the client having declined or failed to respond. Necessity would then be demonstrated rather than assumed, and the question could be brought again.

I make no finding on whether the client should hold `{all: true}` scope, which was not argued.

## Authorities relied on

- [2026] VJS-COUNTY 7 (2026-VJS-CC-BOLTRIG-FIRST-PARTY-AUTH-001.yaml, status: binding) - read in full at /home/jellytot/Projects/boltrig/.vjs/orders/. D7 and the holding at lines 13-15 relied on for the bootstrap-necessity ratio governing host-boundary carve-outs.
- [2026] VJS-COUNTY 9 (2026-VJS-CC-BOLTRIG-AUDIT-DEPTH-001.yaml, status: binding) - holding and D1-D6 read. D3 (distinct tamper-evident SecurityEvent stream) and D6 (append-only, keys-only) relied on for D6 of this order.
- [2026] VJS-COUNTY 10 (2026-VJS-CC-BOLTRIG-SECOND-FACTOR-001.yaml, status: binding) - read in full. D3 relied on only to establish that, with user_totp empty on the subject tenant, the second factor currently does nothing to blunt the set-password boundary route.
- NOT RELIED ON - 'INV-8': cited in the case file's Option 2 as 'an INV-8-class audit row'. Verified to have ZERO occurrences anywhere in the boltrig repository outside the submission itself; it is an opbox kernel invariant resident in the vibe-justice-system repo. No condition has been adopted under that name.

## Scrutiny (invented-authority check)

{
  "sound": false,
  "verdict_note": "The ruling is NOT void. No invented authority (COUNTY 7/9/10 all exist, are binding, and every quoted string is exact; the judge actively guarded against the C1-C9 defect class by refusing to adopt \"INV-8\", which I confirm has zero occurrences in boltrig), no invented condition, and no contradiction in the ratio itself. I re-walked every pleaded code line and it is line-exact, and I queried the live Classical Visas database (SELECT only): the two-author state, the NULL assignees, the 9 operator-only hitl_responses, the [\"*\"] tenant permissions, the empty user_totp, and the 08:19:12->08:30:31 timeline all verify to the second. Finding (A) - that the in-band route is open and untried - is sound, and so is the impersonation finding (set-password writes actor=email at initiate.py:219; mint-token at mint_token.py:80). The defects are confined to the RELIEF and to two limbs of the symmetric case file. Two are serious enough that the order as drafted would be recorded as discharged while the live problem stands: D5 tests two code constants that CV's deployed manifest.yaml overrides, and D8 orders an act the shipped notifier cannot perform while its check can go green without it - and the reserved paragraph makes that green the key to re-arguing the very command refused. D5, D7 and D8 should be re-drafted before the order is filed.",
  "problems": [
    {
      "kind": "unenforceable_directive",
      "detail": "D8 is the most serious defect: it orders an act the shipped code cannot perform, and its check can go green without the act. D8 requires a control.invitation.create to be \"actually PUT TO info@classicalvisas.com\". I read the only notification path: boltrig/kernel/hitl.py:235-252 `_notify_request`, whose subject is `req.assignee or req.requested_on_behalf_of or req.requested_by` (line 244). On CV every one of the 17 live hitl_requests rows has assignee NULL and requested_by = will.lilley93@gmail.com, so an operator-raised request notifies THE OPERATOR and nobody else - by construction, not misconfiguration. It gets worse on the live record: `notification_prefs` on cvboltrig is EMPTY (0 rows), the manifest names `primary_channel: teams` and `notify_via: [teams]` but there is no `teams` row in the `adapters` table, and `notify_via` is parsed at manifest.py:591 and then READ BY NOTHING in the entire codebase. D8 does not direct that an assignee be set, and its checkable clause does not test for one. Its second disjunct - \"a hitl_requests row with verb='control.invitation.create', (timeout_at - created_at) >= 24 hours, and status='timed_out'\" - is therefore satisfiable by raising a request, waiting, and never telling the client it exists. The reserved paragraph then treats a satisfied D8 as a record of \"the client having declined or failed to respond\", which would unlock re-arguing the refused seat-operator command on a record that proves only that a row expired. Fix: D8 must require request.assignee = info@classicalvisas.com AND a delivered notification (or an out-of-band channel named in the order), and the check must assert delivery, not expiry."
    },
    {
      "kind": "contradicts_record",
      "detail": "D5 is aimed at the wrong artefact and can be fully discharged without changing the window that caused this. The judgment says \"The three timed-out requests are evidence of a 3600-second window (manifest.py:177 and :592)\" and D5 makes those two lines the object of the test: \"a test reads the value actually compiled into boltrig/config/manifest.py at BOTH :177 (the dataclass default) and :592 (the raw.get fallback)\". Both lines are indeed 3600 - but neither is the operative value on Classical Visas. I read the deployed file: `docker exec cv-boltrig-kernel-1` shows /app/manifest.yaml (the first candidate in bootstrap.py:28) carries an EXPLICIT `approval_timeout_seconds: 3600` under `hitl:`. manifest.py:592 is `int(raw.get(\"approval_timeout_seconds\", 3600))` - the fallback only fires when the key is ABSENT, and on CV it is present. The value that produced the three timeouts came from the tenant's manifest.yaml, not from either code site. So an engineer can raise both constants to 86400, the prescribed test goes green, and CV keeps its 3600-second window unchanged. manifest.example.yaml:308 also ships 3600 to every new tenant and is named nowhere in D5. This is the \"a check that cannot fail\" class. It also breaks D8: D8's second branch requires (timeout_at - created_at) >= 24 hours \"per D5\", which under CV's unamended manifest is unreachable, so D5 and D8 do not compose."
    },
    {
      "kind": "unaddressed_argument",
      "detail": "The case file's second FOR argument is never engaged, and it bears directly on the relief actually ordered. The submission pleads: \"The alternative is asking the client to approve operator business, training them to approve what they cannot evaluate and degrading every future approval they give.\" That is a distinct argument from the impersonation point the judge selects as \"the strongest argument against refusing\" in section 3, and it is the one that attacks the judgment's own remedy. The judgment's ratio holds that \"the defect is repaired in-band\", and D8 orders the operator to put operator-side business (seating a second operator) to the client for approval. The case file's answer is that this route is adequate in form and corrosive in substance - it converts four-eyes into a rubber stamp on matters the second pair of eyes cannot assess. Section 4 (\"The floor\") addresses the client as a protected third party only for limb 2 (the demotion); it says nothing about the quality or cost of the approvals D8 requires them to give. A symmetric case file was put, and this limb of it is unanswered."
    },
    {
      "kind": "unenforceable_directive",
      "detail": "D7 is direction-agnostic and one of the two cures it permits is destructive and collides with D2. D7 says \"a test asserts the TypeScript set equals the Python set element-for-element (or that the TypeScript set is generated from the Python one) and FAILS on any divergence in either direction.\" I read both sets. Python (rbac.py:163-165) is {superadmin, admin, org-admin, department-head, manager, lead, integrator}; TypeScript (ui/src/deck/deckMap.ts:17-23) is {org-admin, department-head, manager, lead, integrator}. The order does not say which is authoritative, and the primary form of the test is symmetric. An engineer can satisfy D7 by REMOVING superadmin and admin from the Python AUTHOR_ROLES. That would: make _sole_active_author (hitl_response_auth.py:124-139) find ZERO active authors on CV; strip authoring/admin-console authority from superadmin and admin at all six verified can_author call sites (control_channel_ops.py:30, platform_routes/_shared.py:20 and :37, channel_routes.py:423 and :591, control_approval.py:59); and hollow out D2, whose seeded test requires \"a tenant with an active superadmin and an active admin\" to count as two authors. The permitted cure would falsify the ruling's own factual premise. D7 must name the Python set as authoritative and require generation in one direction only."
    },
    {
      "kind": "unaddressed_argument",
      "detail": "Option 3 of the case file - \"Allow it only for an allow-listed operator domain\" - is never named anywhere in the judgment. The judgment expressly disposes of Option 1 (section 1(C)), Option 2 (the INV-8 paragraph), and Option 4 (reserved), which makes the silence on Option 3 conspicuous rather than merely economical. D1's refusal of \"any new host-boundary CLI command that creates a user identity\" does dispose of it on the necessity ratio, so this does not affect the outcome, but on a symmetric case file every enumerated option should be shown to have been weighed - particularly where the judgment takes care to explain why Option 4 is reserved rather than refused."
    },
    {
      "kind": "other",
      "detail": "Internal contradiction in the load-bearing paragraph of the ratio. Section 1(A) reads: 'The case file says \"Every route to a second operator requires an approval that requires a second operator.\" Two sentences earlier it concedes \"the only lawful approver of an operator-raised request is the client.\" Those cannot both be true, and the second is wrong.' On the natural reading, \"the second\" is the second-quoted proposition - that the client is the lawful approver. But the entire finding that follows PROVES that proposition true: the judge walks every gate and concludes \"The route to a second operator is open today, with no code change.\" The proposition shown to be wrong is the first one (\"every route requires an approval that requires a second operator\"). As drafted, the paragraph declares false the exact claim the ratio rests on. Almost certainly a slip for \"the first is wrong\", but it sits in the sentence that carries the refusal and should be corrected before filing."
    },
    {
      "kind": "unenforceable_directive",
      "detail": "D1's second test rests on an undefined term and would fail today as naively written. The first half is exact and checkable - I confirmed cli.py:200 is `if args.cmd not in (\"initiate\", \"set-password\", \"mint-token\")` and that `_add_identity_parsers` exists at cli.py:88. The second half requires \"a test asserting boltrig/api/initiate.py remains the only host-boundary call site constructing a User(...) object\". The order never defines \"host-boundary call site\", and boltrig/api/ contains two other User(...) constructions today: auth_routes.py:181 (which mints a role=\"superadmin\", scope={\"all\": True} User on the org-provision accept path) and auth_routes.py:350. A path-scoped test over boltrig/api/ fails immediately; passing it requires the engineer to invent the boundary definition the order withheld. Worth noting for the reserved question rather than as a defect in the outcome: auth_routes.py:181 creates a superadmin identity over HTTP with no HITL gate, so the proposition that the identity-creating surface is exactly the three CLI commands is narrower than D1's framing implies (it is a different tenant, so it does not disturb the CV finding)."
    }
  ]
}
