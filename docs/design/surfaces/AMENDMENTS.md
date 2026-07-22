# Surface-spec amendments (2026-07-02) - BINDING over the surface specs

The four surface specs in this directory and `../ui-patterns.md` were produced by
parallel design seats and then judged. Where anything below conflicts with a spec,
this sheet wins. Implementing seats read the spec AND this sheet.

## A. Verified kernel facts every surface must honour

1. **Approval does not apply the change.** The HITL gate fires BEFORE execution
   (dispatch.py step 4, `raise PendingHuman` at boltrig/kernel/dispatch.py:212-231);
   the write happens only when the caller re-invokes the SAME verb with the same
   params plus `approval_id`, which is consumed single-use and verb-bound
   (app.py:265-283, consume_if_approved). Therefore the N15 PendingHumanCard
   contract is: on detecting approval, the card re-invokes with identical
   sentParams + approval_id (fresh idempotency key) and renders THAT result union;
   intermediate label "Approved - applying..."; if the params are no longer held
   (cross-session), render "Approved - not yet applied" with an explicit Apply
   action once dependency A3 lands. Any spec text saying a card "flips to ok in
   place" on approval is amended to this.
2. **Every FIRST save of a control.* write 202s.** consequence-high gating is
   deterministic (dispatch.py:213), so the governed SaveBar vocabulary is:
   button "Request change" (busy "Requesting..."), foreshadow "This is a
   high-consequence change. It will pause for a human approval before it takes
   effect." Never "may pause"; never an ok-styled Save as the primary documented
   outcome of the first submit. The automations spec's "Save workflow" button and
   its ok-first treatment are amended accordingly; the ok treatment documents the
   post-approval apply leg.
3. **Approvals carry structured, bounded context.** GET /v1/hitl returns the
   requester, optional on-behalf-of actor, exact verb, run id, resource context,
   and redacted literal inputs. The approval surface renders that structure and
   links to the run. Secret-shaped keys and token-shaped values are redacted at
   the storage boundary, not merely hidden by the UI. This landed as A3 on
   2026-07-21.
4. **Workflow live view uses an early run-id handshake.** Execute remains a
   synchronous HTTP call, but the client mints the run id and passes it in the
   governed invocation context before dispatch. The canvas subscribes immediately,
   retries the initial not-yet-created stream briefly, and keeps the identical
   run context through any approval re-invocation. This landed as A4 on 2026-07-21.
5. **Run on a never-saved draft 404s.** When a workflow has never been saved,
   disable Run with hint "Save the workflow first - runs use the saved version."

## B. Cross-surface coherence rulings

6. **One personal-agent editor.** The canonical home is the settings spec's
   `#/settings/agent` composition (it is the most complete and grounds the
   enabled-field honesty). The agents row's `#/agents/me` slide and the ops Me tab
   mount the SAME shared component or link to it; MePanel keeps invoke-only.
7. **Canonical copy block** (added to ui-patterns.md copy canon):
   - Discard arm: "Discard changes? Your edits since the last save are lost."
   - ByChat control label, always visible: "Do this in chat".
   - Governed save: see amendment 2.
8. **Sidebar dots are row-agnostic:** dirty dot for unsaved drafts, steady amber
   dot for an unresolved pending_human, on every row's map entries.
9. **Invalid-JSON guard is global:** an unparseable JsonDisclosure blocks Save and
   slide navigation on every surface (the one lawful P17 block), not just
   automations.
10. **Tone law enforcement:** amber (consequence) tone ONLY where the kernel
    gate is actually in play. Writes riding ungoverned direct routes (verb
    binding, hierarchy PUT, personal agent POST, invitations, user PATCH) use
    tone=warn until their control.* verb lands, then flip to consequence.
11. **Capabilities fetch policy unified:** one cached /v1/capabilities read per
    slide activation plus refresh-on-write; no per-surface poll cadences for the
    registry.
12. **Register ratifications:** N17 OrderedPicker, N18 SecretOnce, N19 DiffView
    (settings spec section 3) and N17-agents BudgetMeter are ratified into the
    primitive register. The automations parents editor is ratified as an N3
    ChipPicker variant with disabled-candidates-with-reason. The "Duplicate as"
    overflow menu is NOT ratified: use a plain ghost row action with inline
    reveal, matching the bind-verb idiom.
13. **Version bump parity note (P31 registry):** the console auto-bumps workflow
    patch versions on save; control.workflow.upsert defaults version when
    omitted, so the orchestrator must read-then-bump (or the verb gains a
    server-side current-version-bump default, dependency A5).
14. **Trigger nodes are out of scope for the automations row this round:**
    visual-only, never serialized, no step slide, no create affordance on the new
    canvas. Schedule stays validate-only.

## C. Craft amendments (the Principal's bar)

15. **Chat composer keyboard follows the chat convention, not the form rule:**
    Enter sends; Shift+Enter inserts a newline. The quiet hint reads "Shift+Enter
    for a new line." P36's Ctrl+Enter-submit stays for FORM textareas. Rationale:
    the Principal benchmarked OpenWebUI; inverting the universal chat-send
    convention fails the muscle-memory test that P36 exists to protect.
16. **The settings-row grid amendment is ratified:** the settings row gains
    columns, one per section, keyed by section id (#/settings/:section), per the
    settings spec section 0. DESIGN-v2's grid table is amended accordingly.
17. Everything else in the chat and settings specs passed the craft audit
    unamended. The agent-builder and automations specs carry the judge's
    amendments above (items 1-5, 10, 12-14).

## D. Shared backend-dependency ledger (deduplicated)

Landed on 2026-07-21:

- A3. Structured HITL context, bounded persistence, secret redaction, and exact
  requester, verb, inputs, resource, and run projection.
- A4. Early workflow run-id handshake through caller invocation context, with
  immediate stream following and approval-continuous identity.

Remaining or partially landed:

- A1. control.* verbs for the remaining console writes: skill.upsert,
  verb.define, noun.define, binding.set, mcp_server.register, config.upsert
  (+ rollback), hierarchy via config.upsert, user.update, invitation.create and
  invitation.revoke, personal_agent.configure (LOW consequence, recorded
  deviation). First tranche in flight as Beat 3.5.
- A2. account.* low-consequence self-scope verbs (settings/notifications/token
  revoke/session revoke) so chat reaches the account plane.
- A5. control.workflow.upsert current-version-bump default (or orchestrator
  read-then-bump documented).
- A6. Revision payload read: GET /v1/admin/config/{section}/history/{rev} for
  diffs; typed schemas for the four extra manifest sections; a runtimes list
  read; personal-agent configure stops minting a new id and accepts enabled.
- A7. Chat backend gaps (chat spec section 12): rename/retitle, regenerate,
  model or agent picker field, attachments, true run cancel, typed error event,
  fine-grained text deltas, workflow_id on workflow_step events.
