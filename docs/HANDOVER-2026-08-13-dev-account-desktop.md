# Handover — account-first desktop and `dev.boltrig.io`

Date: 2026-08-13

## Outcome

- `https://dev.boltrig.io/`, `/healthz`, and `/readyz` return HTTP 200.
- The hosted Worker presents ordinary server account sign-in. It contains no
  provider credential fields.
- The desktop app uses the same account session as the web client, then creates
  or resumes a separately revocable computer identity in the macOS Keychain.
- Local folders, Bash, and background work remain disabled until the user
  explicitly binds a folder in **Settings → Advanced**.
- The installed development app contains the pinned local Codex CLI 0.144.3.
- The public-product gate permits BYO Bifrost configuration and ships Familiar
  plus Jarvis only. Personal Ollama/M1 routes and other companions are absent.

This is a development deployment and an ad-hoc-signed desktop build. It is not
production signing, notarisation, updater-signing, or design-authority evidence.

## Jellytot deployment

Traffic reaches Jellytot through the existing `beelink-cable` relay:

```sh
ssh beelink-cable "ssh jellytot-prod '<command>'"
```

The static Worker is served by:

```text
systemd unit: boltrig-dev-preview.service
root:         /home/jellytot/boltrig-dev/dist
listen:       127.0.0.1:1420
```

The final deployed HTML digest is:

```text
sha256:4b14efd56107dee7fc657a7d0bc0a965b534c96eda6c3389f770bdd85f8ac0ff
```

The complete 43-file static-tree digest (relative path, NUL, then bytes in
sorted path order) is:

```text
sha256:f252fc4e42d3391d05dfb38118c5efd942fe825712599649ea62991c948770db
```

The API remains the pinned Jellytot dev-kernel container. Do not move this
workload to `beelink-prod`, CV/opbox, or a personal M1/Ollama host. Caddy is the
public HTTPS boundary and includes the two Tauri origins in the development
CORS allow-list.

The immediately previous static tree is retained as:

```text
/home/jellytot/boltrig-dev/dist.previous.20260813-2353
```

Restore by atomically swapping that directory back only if the new static tree
must be rolled back. The API and database were not mutated by the UI deploy.
The current dev backend tree remains separately bound to
`sha256:e2372ed2883c59b70cb3854538cdd1c71cc706a5e71d967b24511b7004c1de5f`;
its rollback is `/home/jellytot/boltrig-dev/backend.rollback-20260813T212518Z`.

## Desktop build

The installed app is:

```text
/Applications/Boltrig Worker.app
```

It was built with the exact development API origin:

```text
https://dev.boltrig.io
```

Its bundled Codex executable reports:

```text
codex-cli 0.144.3
sha256:718724d7221cf1298071ca92411cb74caa8422809154150cedca7b569a4518e3
```

The build generated a valid `.app` and updater archive, then deliberately
failed the updater-signature step because the protected Tauri signing private
key is not present locally. The installed copy was ad-hoc signed solely for
development testing. A production release must use the protected workflow,
Apple notarisation, the Tauri updater key, and the configured HTTPS API/update
origins.

An ad-hoc signature changes whenever the app changes. macOS therefore asks the
user to unlock the existing `io.boltrig.worker` Keychain item again. The user
must enter their own login password and choose **Always Allow**; automation must
not type that password. Stable production signing removes this development-only
prompt churn.

The last build that completed the Keychain and cold-restart smoke is retained
under:

```text
/Applications/Boltrig Worker.previous-finalcopy-20260813-1952.app
```

The immediately previous installed app is also retained as:

```text
/Applications/Boltrig Worker.previous-20260814-0001.app
```

The current app was rebuilt after the password-reset transport and Keychain
single-flight repairs,
installed on 2026-08-14, ad-hoc signed, and passed
`codesign --verify --deep --strict`. Its installed executable digest is
`sha256:25d2707cffc5706976e6f18fd53b5fd0cc3c4b5a00273a0921f5afa3a0db3f49`.
The replaced bundle is retained as:

```text
/Applications/Boltrig Worker.before-password-reset-fix-20260814-0745.app
/Applications/Boltrig Worker.before-keychain-singleflight-20260814-0802.app
```

That replaced build had `https://dev.boltrig.io` in the frontend but no native
`BOLTRIG_DESKTOP_API_ORIGIN`, so password reset rendered correctly and then
failed before reaching the server. Tauri now refuses a missing or mismatched
frontend/native pair, and Cargo tracks native-origin changes. The installed
replacement contains the exact origin in both layers. A non-account desktop
probe reached the reset confirmation screen through the native transport; it
did not send an email. No folder, camera, microphone, or Keychain permission
was granted during this repair.

Other timestamped development backups also exist in `/Applications`; do not
delete them until the final Keychain acceptance and cold restart pass.

## Native transport fixes

The desktop no longer sends API responses over an unbounded Tauri event
channel. Rust returns one versioned binary envelope with bounded metadata and a
32 MiB response cap. The Worker validates magic, status, headers, lengths,
origin, `/v1` path, request size, and abort state before constructing a browser
`Response`.

Keychain access was also moved off the Tauri event loop with a bounded
`spawn_blocking` call. A Keychain prompt can no longer freeze the whole window.
The account bridge, local-agent projection, and background device loop now
share one process-local, mutation-aware read of the `device-session` item. A
changed ad-hoc signature therefore presents one startup authorization prompt,
not one prompt per consumer; denial is cached until restart rather than
immediately asking again. Production signing remains the durable fix for prompt
churn across upgrades.

The TypeScript surface is split into:

- `apps/worker/src/desktop.ts` — account, enrollment, updates, OAuth, roots,
  leases, and artifact wrappers;
- `apps/worker/src/desktopApiTransport.ts` — bounded authenticated native HTTP;
- `apps/worker/src/desktopCamera.ts` — camera discovery and verification.

All three files satisfy the Worker structural ceiling. `desktop.ts` is 372
lines, down from 566.

## Verified behaviour

The hosted browser was signed in with a disposable member account and verified:

- private shell rendering;
- no duplicate Recents search or workspace label;
- Models settings with Text LLM, Vision, and Voice views;
- no browser-side Bifrost provider-key input; Account → Access separately
  exposes the one-shot envelope-sealed legacy provider-native intake described
  below;
- truthful unavailable Bifrost catalogue when no provider is configured;
- truthful plugin availability;
- author-only Agents access denied to a member;
- logout returning to the account sign-in page.

A final superadmin smoke also verified the live Agents, Plugins, Routines,
Autonomy, Health, Camera and presence, Models, command-palette and new-chat
surfaces. The model switcher refuses sends when no default is configured and
now says `No default chat model is configured.` instead of exposing the kernel
reason code. Camera settings now describe Boltrig's ownership boundary without
the broken development sentence. Browser diagnostics were empty. The
disposable account was signed out and all six of its remaining sessions were
revoked after the smoke. It remains an inactive-in-practice but administratively
active second author seat: governed deactivation correctly refused to leave the
tenant with one author and silently revive the sole-author approval exemption.
No temporary PAT remains active. Replace that seat with a real independent
administrator before any production cutover; do not bypass the ratchet or
direct-edit the database.

The desktop also exposed a stale role projection after the account had been
promoted remotely: the shell still said `member` while Settings correctly said
`superadmin`. `WorkerGlobalContextProvider` now refreshes identity and active
context when the browser or desktop regains focus (and when the document becomes
visible). A focused regression proves the account-menu accessible name moves
from the old role to the current role. The rebuilt static bundle containing the
fix is the one currently served by Jellytot.

The desktop was previously verified end to end against the same account:

- account session persisted over a cold restart;
- computer enrollment completed automatically after sign-in;
- native agent reached `ONLINE`;
- no root was silently selected;
- camera inventory remained permission-gated;
- local task input stayed disabled until a folder is deliberately bound.

The final refactored build has the same tested commands and is installed. Its
remaining manual acceptance step is the macOS Keychain prompt, followed by one
cold restart and an `ONLINE` check in **Settings → Advanced**.

## Password recovery and MailerSend

On 2026-08-14 the standard ASGI composition gained a bounded server-only
MailerSend password-reset notifier. The public reset request remains
non-enumerating; only a SHA-256 digest of the one-use bearer is stored. Delivery
uses MailerSend's fixed HTTPS origin, refuses redirects and environment proxies,
disables click/open/content tracking, and has a five-second wall-clock limit.
`/readyz` uses the read-only quota endpoint and still states explicitly that
provider acceptance or inbox delivery is not proven.

Jellytot now requires this readiness check. The active kernel is
`8189ee55032b`; its prior container is retained as
`boltrig-dev-kernel-before-mailersend-20260814-0730`, and the prior backend tree
as `/home/jellytot/boltrig-dev/backend.rollback-mailersend-20260814-0720`.
Public `/`, `/healthz`, and `/readyz` returned HTTP 200 after promotion, with
`password_reset_delivery=ok` and `model_gateway=ok`; startup logs contained no
credential match.

The current MailerSend account exposes only `opbox.app` as a verified sending
domain, so Jellytot uses `noreply@opbox.app` for this development deployment.
That address and the API key exist only in the mode-600 server environment;
neither is present in source, examples, Worker, Tauri, VDS evidence, or the
public-product defaults. A production deployment must verify and use its own
sending domain. Because the initial credential was pasted into a chat, rotate
it after password recovery and replace the server value before treating this as
production evidence.

## Gates

Final local results:

- Worker Vitest: 87 files, 807 tests passed;
- Worker TypeScript: passed;
- focused voice/barge-in: 43 tests passed;
- Tauri Rust: 40 tests passed;
- account/native/camera/public-product Python slice: 35 passed;
- full Python/PostgreSQL suite: 3,822 passed, 161 skipped, 85.38% coverage;
- Worker structural ratchet: passed, 64 debt files and no new debt;
- invariants: 410 declared, 410 marked, 1,682 bound, debt 0;
- public-product: `PASS (BYO Bifrost; Familiar + Jarvis only)`;
- VDS ledgers: 14 screens, 1,682 references, 6 routes, source-current;
- `git diff --check`: passed.

Current visual evidence is bound to Worker/visual source digest:

```text
abf7be9a1711d3423cd925604f32192b9c528eaa2e59477a22b7f036b80abf83
```

It remains `not_assessed`. All six route reviews are unsigned
`no_authority`; SCR-0007 still lacks a non-invented full-depth frame digest.
No sign-off, conformity verdict, or frame digest was fabricated.

## Remaining external work

1. Complete the final macOS Keychain prompt and cold-restart acceptance.
2. Configure a non-personal Bifrost provider through the server-owned secret
   path before expecting cloud model calls. The current empty catalogue is
   truthful. The Account sealed-key form is a legacy provider-native seam, not
   Bifrost administration and not a substitute for this step.
3. Bind a disposable test folder before exercising local Bash/file work. Never
   choose a personal folder implicitly.
4. Use protected signing/notarisation/update credentials for a distributable
   desktop release.
5. Production release, recovery, monitoring, Codex production admission, and
   channel egress remain separate fail-closed release gates.
6. Rotate the development MailerSend credential after the account password has
   been recovered; do not copy this development secret into production.

## Jellytot BYO cleanup and live acceptance

On 2026-08-13 the development kernel on `jellytot-prod` was recreated from its
existing immutable image with the current bind mounts and persistent volumes,
but without legacy `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` entries. Removing a
line from `backend.env` is insufficient: Docker retains the old environment in
container metadata. The active container was replaced and six stopped rollback
containers that still held those variables were removed. Database, Bifrost,
Hatchet and CV/opbox containers were not restarted or changed.

`BOLTRIG_MODEL_GATEWAY_HEALTH=1` is now set for the development kernel. Both a
side-by-side candidate and the final replacement reported `model_gateway=ok`,
and the public `/`, `/healthz` and `/readyz` endpoints returned HTTP 200. The
organisation's `allow_own_ai_keys` flag was changed through
`PATCH /v1/orgs/current`, using two distinct active administrators for the
request and approval; the temporary host-boundary PATs were revoked.

The Bifrost catalogue still contains zero models and no AI-key rows were seeded.
That is deliberate: the hosted preview now carries no repository-owner model
credential and will refuse cloud sends until an operator configures Bifrost.
The live static bundle contains Familiar and Jarvis literals and no Maya literal.

Final readback receipts:

```text
dev kernel container       8189ee55032b
backend relative-tree hash e2372ed2883c59b70cb3854538cdd1c71cc706a5e71d967b24511b7004c1de5f
static relative-tree hash  f252fc4e42d3391d05dfb38118c5efd942fe825712599649ea62991c948770db
organisation BYO policy    allow_own_ai_keys=true
active temporary dev PATs  0
active disposable sessions 0
active author-tier users   2 (required for independent approval)
Bifrost advertised models  0
```

The backend tree hash is SHA-256 over sorted tracked/non-ignored paths encoded
as `relative-path NUL file-SHA LF`; the static tree uses the equivalent deployed
relative-path/file-SHA stream. The local repository and Jellytot returned the
same value for each tree.
