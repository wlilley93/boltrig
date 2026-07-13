# Chokepoint totalization - migration plan

> Vision program item #1 (all three engine-review lenses converged on it): make the "ONE
> dispatch chokepoint" claim literally true for the whole platform, not just actions. Today
> ~26 direct `k.store` writes in `kernel/access_routes.py` and `kernel/channel_routes.py` sit
> on a hand-rolled `_require_admin` + local `_audit` plane. This plan categorizes every one and
> sequences the migration. **Not yet approved for execution** - it changes the live console's
> HTTP contract, so it needs your go-ahead per group. Generated 2026-07-13 (read-only analysis
> + adversarial verification). SEC-51 / `tests/invariants.yaml:740` already mandates governed
> config writes; `dispatch_control_route` already routes some.

## The 26 sites

**MIGRATE to a governed `control.*` verb (14)** - config/authoring writes, the SEC-51 class:

| Site | Verb |
|---|---|
| `access_routes.py:696-697` set_ai_key | `control.ai_key.set` |
| `access_routes.py:724-725` delete_ai_key | `control.ai_key.delete` |
| `access_routes.py:904` update_current_org | `control.org.update` |
| `access_routes.py:942-943` create_workspace | `control.workspace.create` |
| `access_routes.py:963` update_workspace | `control.workspace.update` |
| `access_routes.py:1012` add_workspace_member | `control.workspace.member.add` |
| `access_routes.py:1026` remove_workspace_member | `control.workspace.member.remove` |
| `access_routes.py:866` revoke_invite | `control.invitation.revoke` |
| `channel_routes.py:276+283` channel_connect | `control.channel.connect` |
| `channel_routes.py:308` channel_configure | `control.channel.configure` |
| `channel_routes.py:320` channel_disconnect | `control.channel.disconnect` |
| `channel_routes.py:356` channel_pair | `control.channel.pair` |
| `channel_routes.py:385` channel_bind | `control.channel.bind` |
| `channel_routes.py:413` delete_binding | `control.channel.unbind` |

**STAY DIRECT BY DESIGN (11)** - self-scoped or ingress writes where ungated is *correct*:
`revoke_my_token` / `revoke_my_session` (self-scoped credential revocation - HITL-gating would be
a security regression), `cancel_run` (owner-only cooperative cancel), `switch_active_context` /
`switch_active_org` (self-scoped session state, re-authorized every request), `put_settings`
(per-user preference), `delete_my_conversation` / `rename_my_conversation` / `regenerate_message`
(owner-only personal data, personal plane not config plane), `channel_inbound` create_work_item
and `_consume_pairing` binding (signed-webhook INGRESS, no principal, authenticated by the
channel signature).

**COURT (1)** - `access_routes.py:904` the security-relaxing org toggles (`require_two_factor`
true->false, `allow_own_ai_keys` enabling member-owned keys): first-impression on whether
*relaxing* an org security posture deserves a distinct HIGH-consequence (HITL-held) tier. This is
a `not my call - the court` item; the org.update migration lands the non-security fields low and
holds these two behind the ruling.

## Ordered PR-sized groups

1. **`invitation.revoke`** (smallest; establishes the lifecycle-completion pattern) **+ land the
   enforcement invariant** seeded with the full current write-set allowlist, so from PR1 on no new
   unsanctioned direct write can enter and the allowlist only shrinks. Frontend risk: LOW.
2. **AI keys** (`set` + `delete`). Keep consequence=low to preserve the synchronous 200 the
   AI-keys screen expects; never surface `api_key` in verb output or run events. Risk: MEDIUM.
3. **Org update.** Keep `{organisation: _org_view}` identical; name/slug/settings land low; the
   2FA/own-keys tier waits on the court ruling. Risk: HIGH (gated on court).
4. **Workspaces** as one noun family (`create/.update/.member.add/.member.remove`). Auto-inherits
   the `rbac.py` `control.workspace.*` owner-only ceiling; `_authz_manage_workspace` 403/404
   pre-checks stay in the route ahead of dispatch. Risk: MEDIUM.
5. **Channels** as one noun family (`connect/.configure/.disconnect/.pair/.bind/.unbind`), the
   largest surface. Routes re-stamp 201 where they do today; the one-time pairing code returns to
   the caller once and is redacted from audit/run events (SEC-76 treatment). Risk: HIGH (channels
   console screen).
6. **Close-out.** The AST allowlist now holds only the stay-direct sites; extend the SEC-75 parity
   suite so every new verb path and its compatibility route assert identical store state + identical
   JSON body + status code, and add every new HIGH verb to the HITL-held-writes-nothing test.

## Enforcement invariant (lands in PR1)

New `test_control_write_chokepoint.py` (modelled on the `test_severability.py` AST scan): parse
both route files with `ast`, collect every `k.store` / `kernel.store` mutating call
(`^(upsert|update|create|add|remove|delete|set|mark|request|bump|consume)_`), and assert each site
is in a frozen `SANCTIONED_DIRECT_WRITES` allowlist keyed by (module, function, method) that
enumerates *exactly* the 11 stay-direct sites. Any new mutating `k.store` call outside the list
fails CI; each migration PR deletes its now-migrated entries, so **the shrinking allowlist is the
enforced progress metric** and the ratchet only ever moves toward the one chokepoint.

## Frontend-contract risk (the reason this needs sign-off)

`dispatch_control_route` can return `202 {status:pending_human}` where direct routes return
`200/201 {status:ok}` (only when a migrated verb is HIGH - concentrated on `control.org.update`),
and it defaults to a 200 the caller wraps, so routes returning 201 (channel connect/pair/bind) or
rich bodies must have the verb output carry the exact keys and re-stamp the status. Secret-bearing
outputs (AI api_key, channel signing secret, one-time pairing code) return to the caller only where
they do today and are redacted from audit/run events. Parity is proven by extending the SEC-75
suite. Fail-closed 403/404 authz pre-checks stay in the route ahead of dispatch, so every denial
shape the console already handles is unchanged.

## Recommendation
Greenlight **Group 1** as the pilot (lowest risk, and it installs the enforcement ratchet that
freezes the debt from growing). Route the **court** item (org security-posture relaxation tier)
before Group 3. Groups 4-5 touch live console screens, so each wants a real-browser parity check
(the SEC-75 suite + a drive of the workspaces/channels screens) before merge.
