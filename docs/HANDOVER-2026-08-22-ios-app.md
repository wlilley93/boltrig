# Boltrig iOS and mobile web handover (2026-08-22)

This document has two parts. Part 1 is the assessment written on the M4 on 22 August 2026 by the
session that built the first SwiftUI prototype, reproduced as handed over (dashes and quotes
normalised and four test paths qualified with `apps/worker/`, nothing else changed). Part 2 records what the `feat/ios-app` branch then did about
it, where the assessment was wrong, and the decisions taken. Read Part 2 first if you are picking
this up; Part 1 is the record.

The prototype referred to in Part 1 lived at `/Users/williamlilley/Documents/ChatGPT/Boltrig` on
the M4 and is now `ios/` in this repository. The M4 also has an untouched Xcode template project
at `/Users/williamlilley/Projects/Boltrig` (SwiftData template, "Initial Commit" 2026-08-21 19:20)
which is NOT the app; both M4 copies are superseded by `ios/` here.

---

# Part 1: the assessment as handed over


**Date:** 22 August 2026  
**Status:** Assessment complete; implementation has not started beyond the existing SwiftUI MVP.  
**Objective:** Turn Boltrig's existing iOS-style mobile web experience into a production-quality iPhone app without losing authentication, onboarding, settings, governed chat, or companion functionality.

## Executive decision

Boltrig already ships a deliberate iOS-style mobile web experience at [https://dev.boltrig.ai](https://dev.boltrig.ai). It is the correct visual and behavioural source of truth for the iPhone app.

The mobile website is not, however, the complete Boltrig product on a phone. It has dedicated mobile implementations for authentication, onboarding, Today, Chat, and Settings. The wider product surfaces, including Agents, Plugins, Browser, Routines, Channels, Build, Evaluations, Runs, Work, Knowledge, Memory, and parts of Organisation, remain primarily desktop console experiences.

The current native SwiftUI project is a prototype rather than a port. It should not be submitted as the public app in its current form. The recommended route is a staged hybrid-to-native migration:

1. Use the existing mobile website immediately for browser and home-screen testing.
2. Use a hybrid shell for early internal TestFlight builds where this accelerates authentication, onboarding, settings, and companion parity.
3. Build the durable product surfaces natively in SwiftUI, beginning with authentication, Today, Chat, and Settings.
4. Keep the animated companion renderer in an isolated `WKWebView` initially, then consider a Metal renderer only after product parity is established.
5. Add native iOS value before public App Store submission, including secure sessions, universal links, push notifications, native attachments and sharing, haptics, and appropriate background behaviour.

Apple's current minimum-functionality rule requires an App Store app to offer more than a repackaged website: [App Review Guideline 4.2](https://developer.apple.com/app-store/review/guidelines/).

## Code and deployment locations

### Native iOS project

The local iOS project is located at:

```text
/Users/williamlilley/Documents/ChatGPT/Boltrig
```

Important files are:

- `Boltrig/BoltrigApp.swift`, which creates the shared `AppStore`.
- `Boltrig/ContentView.swift`, which provides the Today, Chat, and Settings tabs.
- `Boltrig/AppStore.swift`, which owns preview data, connection state, and the limited live API workflow.
- `Boltrig/BoltrigAPI.swift`, which implements the current four API interactions.
- `Boltrig/TodayView.swift`, `Boltrig/ChatView.swift`, and `Boltrig/SettingsView.swift`, which implement the current native surfaces.
- `Boltrig.xcodeproj`, which targets iOS 17 or later with bundle identifier `com.williamlilley.Boltrig`.

The existing device, TestFlight, and App Store launch guide is at `output/pdf/Boltrig_Xcode_iPhone_Quick_Guide.pdf`.

### Boltrig web and server source

The main remote machine is reached with:

```bash
ssh beelink-cable
```

Relevant remote locations observed during the audit were:

```text
/home/jellytot/Projects/boltrig
/home/jellytot/boltrig-fixtree
/home/jellytot/boltrig-structure
/home/jellytot/Projects/boltrig-companion
/home/jellytot/Projects/boltrig-familiar-web
```

The product web client is under `apps/worker` in the complete Boltrig worktrees. The focused audit used `/home/jellytot/boltrig-structure`. Its key mobile files were byte-for-byte identical to `/home/jellytot/boltrig-fixtree` at the time of inspection, except that `AppRouteSurface.tsx` selected a different Integrations component. That difference did not affect the dedicated mobile surfaces.

The latest inspected `boltrig-fixtree` commit was:

```text
154d4c5d 2026-08-22 05:49:01 +0000
branch: bench-unified
```

The checkout at `/home/jellytot/Projects/boltrig` was 23 commits behind its remote tracking branch during the audit. Before changing the web app, establish which worktree and commit are the deployment source of truth. Do not assume that `/home/jellytot/Projects/boltrig` is current merely because of its name.

The deployed development host is:

```text
https://dev.boltrig.ai
```

## What was verified

The live deployment was inspected at an iPhone-sized viewport of 393 by 852 pixels. The login screen rendered cleanly with no browser warnings or console errors.

The deployed bundle contains:

- A dedicated mobile palette based on iOS system-style colours.
- Safe-area handling for the notch, home indicator, and horizontal insets.
- Forty-four-pixel touch targets.
- Dedicated Today, Chat, and Settings components.
- The complete onboarding flow and all four companion choices.
- A web manifest with `display: "standalone"`, app icons, and an Apple touch icon.

The deployed bundle did not contain a service-worker registration. The current home-screen web app therefore must not be described as offline-capable, and no web-push implementation was found.

The following focused test suites were run against the inspected web source:

```bash
ssh beelink-cable \
  "cd /home/jellytot/boltrig-structure && \
   pnpm --pm-on-fail=ignore --dir apps/worker exec vitest run \
   apps/worker/tests/mobileChat.test.tsx \
   apps/worker/tests/mobileSettings.test.tsx \
   apps/worker/tests/onboarding.test.tsx \
   apps/worker/tests/responsiveHardening.test.ts \
   --reporter=dot"
```

The result was 45 passing tests across four passing test files. These tests cover mobile Chat behaviour, mobile Settings parity, onboarding, safe-area handling, touch target sizes, reduced-transparency fallbacks, and compact layout behaviour. No dedicated `MobileToday` component test was found.

## Existing mobile web architecture

The application deliberately treats a phone as a separate product surface rather than squeezing the desktop console.

- `App.tsx` considers widths at or below 640 pixels to be phones.
- `App.tsx` switches to compact navigation at or below 760 pixels.
- `AppRouteSurface.tsx` renders `MobileToday` for Home on a phone.
- `AppRouteSurface.tsx` renders `MobileSettings` for Settings on a phone.
- `ChatView.tsx` renders `MobileChat` at the phone breakpoint.
- `MobileChatParity.css` and the mobile section of `styles.css` implement safe areas, iOS-style colours, touch sizing, mobile typography, and the fixed composer.
- `AuthGate.tsx` wraps the entire private application.
- `OnboardingGate.tsx` blocks entry until the current onboarding version has been saved.

The TypeScript SDK at `sdks/web/src/client.ts` is the most complete client contract. It is not directly reusable from Swift, but its endpoint behaviour and types should be treated as the reference when implementing the native client.

## Functional assessment

| Area | What already works on mobile web | Work still required for a complete iPhone app |
|---|---|---|
| Authentication | Sign-in, invite acceptance, password recovery, required password changes, two-factor challenges, and two-factor enrolment are implemented. | The SwiftUI app has none of these flows. Native session storage, CSRF handling, refresh, logout, Keychain storage, and universal links are required. |
| Onboarding | A six-step flow collects the user's name, companion, text provider, optional vision provider, optional voice provider, and completion state. The server persists the profile and settings. | The entire flow must be ported or hosted temporarily in a web view. Provider credentials must continue to go directly to the Boltrig server and must never be logged or stored in app preferences. |
| Today | The dedicated mobile screen loads pending HITL requests and open conversations, supports Approve and Not now, opens conversations, starts a chat, and opens Settings. | "Working now" is currently inferred by taking the newest conversation, not by reading authoritative run state. Earlier conversations are capped at twelve. There is no pagination, pull-to-refresh, polling, or visible load-error state. |
| Chat | The mobile chat renders durable and live messages, plans, tool disclosures, subagents, approvals, questions, queued messages, stop, reconnect, task details, and existing attachment names. | The phone composer currently sends text with an empty attachment list. It does not expose file or photo attachment creation, model choice, dictation, voice calls, or the full companion stage. Native SSE parsing must handle the complete event vocabulary rather than only `text_delta`. |
| Settings | The phone has an iOS-style Settings list, search, back navigation, and the same server-backed section panes as the console. Appearance, companion selection, accessibility, behaviour, autonomy, spending, models, health, organisation, advanced controls, and archived chats are represented. | Notification routing, quiet hours, voice choice, transcript retention, dictation, calls, and hold-at-gate controls are currently disabled or unavailable. Desktop-specific rows such as keyboard shortcuts and local-device controls need mobile-specific treatment. |
| Companions | Familiar, Jarvis, Ultron, and Colossus can be selected during onboarding. Their previews, skins, and voice samples are present, and the account stores the selected character. | The post-onboarding phone surfaces hide the sidebar companion switcher and the full Stage. Mobile Today and Chat mostly show lightweight Familiar badges, regardless of the selected top-level companion. The mobile information architecture needs a persistent, intentional place for the selected companion. |
| Wider product | The application has routes for Agents, Plugins, Browser, Routines, Channels, Build, Evaluations, Runs, Work, Knowledge, Memory, Organisation, and other control-plane features. | These are not part of the dedicated iOS-style phone journey. Some have responsive CSS, but they remain desktop console surfaces and should not be claimed as mobile parity. |

## Known web issues to resolve or consciously accept

1. `MobileToday` uses the newest conversation as "Working now" because the summary lacks authoritative per-conversation run state.
2. `MobileToday` shows at most twelve earlier conversations and does not paginate.
3. `MobileToday` silently suppresses loading failures.
4. `MobileToday` has no focused component test.
5. The mobile chat composer cannot create attachments.
6. The mobile chat omits model selection, voice, dictation, and the full companion Stage.
7. Several Settings controls are honest but disabled placeholders.
8. `ReadyStep.tsx` names Jarvis correctly but calls every other selected character "Familiar," so Ultron and Colossus are misnamed on completion.
9. `OnboardingGate.tsx` preserves a previously stored Jarvis choice but otherwise falls back to the default Familiar when onboarding starts. This does not preserve a stored Ultron or Colossus choice.
10. The mobile surfaces hide the compact navigation button, so the dedicated phone journey cannot naturally reach most desktop product routes.
11. The standalone web app has no service worker, offline mode, or discovered web-push implementation.

## Current SwiftUI state

The native app already has a useful structural start:

- A SwiftUI `TabView` for Today, Chat, and Settings.
- A native Today layout with approval actions and conversation rows.
- A native chat layout with a back control and text composer.
- A native Settings list with search and detail navigation.
- Calls to `GET /v1/conversations`, `GET /v1/hitl`, `POST /v1/hitl/{id}/respond`, and `POST /v1/chat`.
- Basic parsing of `text_delta` events from the chat response.
- Preview data for simulator and disconnected use.

The important limitations are:

- `AppStore.bootstrap()` performs no authentication or initial data load.
- The server URL defaults to `http://127.0.0.1:18000`, not `https://dev.boltrig.ai`.
- The server URL is written to `UserDefaults` and exposed as an editable field.
- The optional bearer token is held only in memory.
- There is no Keychain integration.
- The app has no login, logout, session refresh, invitation, password recovery, password-change, or two-factor flow.
- The app has no onboarding flow.
- The app has no companion model, selection, skins, Stage, or companion persistence.
- Settings mostly display labels or placeholder values instead of reading and mutating server state.
- Chat only extracts assistant text. It does not model runs, steps, tool receipts, HITL questions, subagents, queues, artifacts, continuity, or reconnect cursors.
- The current chat request waits for `URLSession.data(for:)` to finish rather than exposing incremental SSE updates to the UI.
- The project contains no asset catalogue or app icon at the time of this handover.

## Recommended architecture

### Native application shell

Use SwiftUI system patterns rather than translating web CSS literally:

- Use `NavigationStack` for hierarchical navigation and native back behaviour.
- Use `List`, `Section`, and inset-grouped styling for Settings.
- Use semantic system colours such as `Color(.systemBackground)`, `Color(.secondarySystemGroupedBackground)`, `Color.secondary`, and `Color(.separator)`.
- Use SF Symbols by name.
- Respect Dynamic Type, VoiceOver, reduced motion, high contrast, safe areas, keyboard avoidance, and minimum touch targets.

The existing web layout is the source of truth for information hierarchy and behaviour, not for pixel-for-pixel CSS values.

### Authentication and API client

Implement authentication before porting additional private screens. Every downstream surface depends on a reliable signed-in session.

The native client should implement the same behaviours exposed by the web SDK:

- `login`
- `twoFactorChallenge`
- two-factor enrolment and verification
- `requestPasswordReset`
- `confirmPasswordReset`
- `acceptInvite`
- required password change
- `refreshSession`
- `logout`
- `meSettings`
- `updateMeProfile`
- `putMeSettings`

Use `URLSession` with a deliberate first-party session and CSRF design. Store only revocable device or session material in Keychain. Do not expose a production bearer-token text field. Do not assume that cookies created in `WKWebView` automatically share state with a separate native `URLSession`; choose one session owner and explicitly bridge only if a hybrid flow requires it.

### Chat transport and model

Replace the current final-response parser with an incremental SSE client. Port the event model from the TypeScript SDK rather than inventing a second event vocabulary.

The native chat state needs to represent:

- Conversation identity and status.
- Durable messages and live text.
- Run identifiers and reconnect cursors.
- Plans and per-step state.
- Tool calls, tool results, and compact evidence.
- Subagents and Familiar genotypes.
- HITL approvals and questions.
- Queued messages, ordering, and steering.
- Stop, reconnect, retry, and continuity notices.
- Artifacts, downloads, previews, and native sharing.
- Attachments selected from Files, Photos, camera, and share extensions as appropriate.

### Companion renderer

Do not begin by rewriting four shader-driven companion renderers in Metal.

The first production-capable design should use a small, isolated `WKWebView` or packaged web scene solely for companion rendering. Native SwiftUI should own navigation, controls, accessibility text, settings, and application state. The renderer should receive a narrow, versioned state payload containing the selected character, skin, run state, speaking level, and any permitted phenotype data.

Reassess a Metal port only after measuring launch time, frame rate, memory, battery use, accessibility, and App Review behaviour on real devices.

### Hybrid boundary

An early TestFlight build may host the entire existing web client in `WKWebView` to prove authentication and end-to-end behaviour. This is a temporary delivery tactic, not the desired public architecture.

For the public app, the recommended long-term boundary is:

| Native SwiftUI | Temporary or isolated web content |
|---|---|
| Authentication shell, universal links, Today, Chat, Settings, notifications, attachments, sharing, downloads, Keychain, app lifecycle, and accessibility. | Companion WebGL rendering and any not-yet-ported administrative console surface that is deliberately offered as an advanced fallback. |

## Implementation sequence

### Phase 0: Establish the source of truth

1. Identify the exact commit currently deployed to `dev.boltrig.ai`.
2. Select the canonical remote worktree and branch for mobile-web fixes.
3. Record the API base URL through build configuration rather than a user preference.
4. Decide whether the first iOS release covers only the mobile core or attempts to expose the desktop control plane. The recommendation is to release the mobile core first.
5. Add focused tests for `MobileToday` and the Ultron/Colossus onboarding completion names.

**Exit condition:** A recorded deployment commit, a stable API contract, and a green focused web test suite.

### Phase 1: Native authentication foundation

1. Create an environment configuration with `https://dev.boltrig.ai` for development and a separate production host when available.
2. Add an `AuthenticationCoordinator` or equivalent state machine.
3. Implement sign-in, session restoration, refresh, logout, password recovery, invitation handling, required password changes, and two-factor flows.
4. Add Keychain-backed secure storage.
5. Add universal-link handling for invitation and password-reset URLs.
6. Gate all private tabs behind authenticated account state.

**Exit condition:** A new invited user can install the app, accept an invitation, complete required account security, sign in again after relaunch, and sign out without entering a server URL or bearer token.

### Phase 2: Native onboarding

1. Port the six-step onboarding state machine.
2. Reuse server catalogues for provider, model, vision, and voice choices.
3. Preserve server-side credential handling.
4. Embed the companion renderer for selection and skin previews.
5. Persist the onboarding version, display name, selected companion, and appearance through the existing account settings APIs.

**Exit condition:** A first-time user cannot reach Chat until the server confirms onboarding completion, and all four companion names persist correctly.

### Phase 3: Native Today and governed Chat

1. Replace preview bootstrap with authenticated loading.
2. Use authoritative run state for "Working now."
3. Add pagination, pull-to-refresh, visible errors, and background refresh appropriate to iOS.
4. Implement incremental SSE and the complete event model.
5. Add inline approvals and questions, queued messages, stop, reconnect, task details, artifacts, and native attachments.
6. Add the selected companion's intentional mobile presence.

**Exit condition:** The native app can complete the same governed conversation and approval flows as the dedicated mobile website without falling back to preview data.

### Phase 4: Native Settings parity

1. Port the server-backed Settings registry and search behaviour.
2. Implement appearance, companion, behaviour, autonomy, spending, models, health, organisation, advanced, and archived-chat sections.
3. Remove, redesign, or clearly label desktop-only rows.
4. Do not present disabled controls as complete features. Either wire them or defer them visibly.

**Exit condition:** Every displayed control either performs its documented server mutation or is explicitly read-only with truthful availability copy.

### Phase 5: iOS value and public release readiness

1. Add APNs-backed approval and completion notifications.
2. Add Face ID or device authentication where it improves access to stored session material.
3. Add Files, Photos, camera, share-sheet, and document-preview integration.
4. Add haptics for approvals, failures, and completed actions where appropriate.
5. Add background status refresh without pretending long-running server work executes on-device.
6. Add the app icon, privacy declarations, support and privacy URLs, reviewer credentials, account-deletion handling, and complete App Store metadata.
7. Test on physical iPhones across supported sizes, connectivity changes, notification states, reduced motion, VoiceOver, and large Dynamic Type.

**Exit condition:** The app provides meaningful native utility beyond a web wrapper and is ready for external TestFlight review followed by App Review.

## Immediate next engineering task

Implement the native authentication and session foundation before adding more screens.

The concrete first slice should be:

1. Replace the editable connection setup with an environment-defined `https://dev.boltrig.ai` base URL.
2. Add Keychain storage and a session state machine.
3. Implement sign-in and session restoration against the same first-party auth contract used by the web SDK.
4. Render the existing `ContentView` only after authentication succeeds.
5. Keep the current preview workspace available only through an explicit debug build configuration.

This slice unlocks real user identity, onboarding, server-backed settings, companions, and trustworthy App Store testing. Adding additional placeholder screens before it would increase visual scope without solving the application's central integration boundary.

## Open decisions

The next owner should obtain explicit decisions on the following points:

1. Which Git branch and commit are authoritative for `dev.boltrig.ai` deployments?
2. What will the production API and web hostname be?
3. Will the first App Store release cover the mobile core only, or must it expose advanced control-plane surfaces?
4. Will companion rendering remain WebGL-in-`WKWebView` for version one, or is a Metal rewrite a release requirement?
5. Which notification events should be delivered through APNs, and what backend device-token contract will be used?
6. What is the exact in-app account-deletion and data-retention flow?
7. Is iPad a supported first-release target or should the initial target be iPhone only?
8. Will public registration remain invite-only?

## Safety and product constraints

- Never store provider, integration, or permanent bearer credentials in `UserDefaults`.
- Never print credentials, session cookies, CSRF tokens, invitation tokens, reset tokens, or chat attachments to logs.
- Never infer authority or capability in the client. The server remains authoritative and the app must show its denial faithfully.
- Never mark work complete merely because the UI optimistically changed. Reconcile approvals and settings with the server response.
- Never describe a polling snapshot as live execution.
- Never claim offline support until an intentional offline data model exists.
- Never identify the newest conversation as currently running without authoritative run state.
- Never treat the standalone web manifest as sufficient App Store-native functionality.

## Summary for the next owner

The hard design work for a good Boltrig phone experience already exists in the mobile website. Authentication, onboarding, governed chat, Settings structure, and companion selection are real and tested. The current native app has the correct top-level SwiftUI shape but only a thin subset of the contract.

The next owner should not redesign the app from scratch and should not attempt a wholesale shader rewrite. They should establish the canonical deployed source, implement native authentication and secure session handling, port the proven mobile information architecture into SwiftUI, and use a narrow web-rendering island for companions until native product parity is secure.

---

# Part 2: what the `feat/ios-app` branch did, and what it found (2026-08-22)

## Where the code is now

- `ios/` holds the native app, restructured from the prototype and rebuilt around a real session.
  It is a two-target Xcode 26 project (app + XCTest bundle) using synchronized folders, so a new
  Swift file needs no project edit. `ios/README.md` has the build and test commands.
- Builds were verified on the M4 over the cable with Xcode 26.6 against the iPhone 17 simulator
  (see the test ledger below for the measured result). The beelink cannot compile Swift; the M4
  is the iOS build box. A scratch copy used for those builds sits at
  `/Users/williamlilley/Projects/boltrig-ios-build/ios` on the M4; the repository is the source.
- Branch base: `origin/main` at v0.4.42 (`76d0944e`). The assessment's worktrees
  (`boltrig-structure`, `boltrig-fixtree`) were on `bench-unified`, 279 commits behind main;
  nothing from them was used.

## Corrections to Part 1

1. **There is no `GET /v1/me`.** "Who am I" is `GET /v1/me/settings` (profile, active workspace,
   settings bag). The app reads `setup.onboarding_version` and `agent.character` from it.
2. **Conversations DO carry authoritative run state.** `GET /v1/conversations` rows include
   `working` (server-owned, see `boltrig/kernel/conversation_list_views.py`). The "newest
   conversation is Working now" inference in Part 1 is a defect of the web `MobileToday`
   component only (`apps/worker/src/components/MobileToday.tsx`, which destructures the first row);
   the native app uses the flag and nothing else.
3. **The session is cookie-based and not the right shape for a phone.** `boltrig_session` is
   HttpOnly, SameSite=Strict, 12 hour sliding life, 7 day absolute cap, with a double-submit
   CSRF header `x-boltrig-csrf` on every write. The kernel also accepts
   `Authorization: Bearer boltrig_pat_...` personal access tokens (`POST /v1/me/tokens`,
   90 day default, 365 max, revocable at `DELETE /v1/me/tokens/{id}`), which bypass CSRF.
   That is the credential the phone keeps.
4. **The web client's API base is not a user preference either**: `VITE_API_BASE` is baked at
   build time (`apps/worker/src/apiOrigin.ts`), and the desktop build refuses to start without a
   matching `BOLTRIG_DESKTOP_API_ORIGIN`. See "The instance question" below for why the phone
   deliberately does allow a different instance.
5. **No service worker, no web push, no APNs, no device pairing, no QR** anywhere in the repo.
   Confirmed, not assumed: the device enrolment routes (`boltrig/kernel/device_routes.py`) are
   for a desktop executor that polls the hosted kernel, not for a phone.

## The sign-in design that shipped

Ceremony on a throwaway cookie session, then a per-phone token:

1. `POST /v1/auth/login` with email and password. Four outcomes are handled: `ok`,
   `2fa_required` (challenge token, no session yet), `password_change_required` (clamped
   session), `2fa_enrollment_required` (clamped session).
2. Screens exist for the two-step code (`POST /v1/auth/2fa/challenge`), the forced password
   change (`POST /v1/auth/change-password`, twelve-character minimum checked on the phone
   first), two-step setup (`POST /v1/auth/2fa/enroll`, otpauth link for authenticator apps,
   key shown for manual entry, `POST /v1/auth/2fa/verify-enroll`) and the one-time recovery
   codes.
3. `POST /v1/me/tokens` with the CSRF header mints the phone token, named
   "iPhone app, signed in YYYY-MM-DD" so it is recognisable in the web token list. The secret is
   stored in the Keychain (`kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`), the cookie
   session is closed with `POST /v1/auth/logout`, and `GET /v1/me/settings` loads the account.
4. A clamp the server still holds after step 3 (403 `password_change_required` or
   `two_factor_enrollment_required`) routes back into the ceremony instead of failing.
5. Launch: token present and instance unchanged, then `GET /v1/me/settings`; 401 or 403 clears
   the token (revoked or expired), a network failure shows "could not be reached" and keeps it.
6. Sign out: `DELETE /v1/me/tokens/{id}` with the token, then forget it.

Trade-offs, stated: a 90 day token outlives the 7 day web session, so a lost unlocked phone
keeps access until the token is revoked from the web token list or expires. Device-bound
Keychain storage means a backup restore onto another phone does not carry it. Face ID gating
and a shorter lifetime are the obvious next hardening steps. Password rotation on the web
revokes sessions but the code was not checked for whether it also revokes PATs; assume it does
not until read.

## The instance question (Will, 2026-08-22)

Will asked whether the phone should connect to a person's own Tauri desktop instance, like a
remote control, rather than to the hosted site, and whether Boltrig might ship only a desktop
app and an iPhone app. What the repository says today:

- The Tauri desktop app (`apps/worker/src-tauri`) is a WebView over the HOSTED kernel. It bundles
  no backend: `tauri.conf.json` points `frontendDist` at the same Vite bundle the web image
  ships, its CSP allows `connect-src` only to the boltrig origins, and the only bundled binary is
  the pinned Codex CLI driven over stdio with no listener (`apps/worker/src-tauri/src/lib.rs`).
  Its origin is compiled in (`apps/worker/src-tauri/src/desktop_account.rs`).
- So "connect to someone's Tauri instance" has nothing to connect to. It would need: a listener
  on the desktop, discovery and pairing (QR or code), mutual auth between two client devices,
  TLS for a LAN origin, an off-LAN relay (phones are on cellular), a way to send push
  notifications without shipping the APNs key inside a desktop app, and a Tauri iOS target.
  None exists. The desktop would also have to run the whole stack (postgres, redis, kernel,
  fleet-worker, hatchet) that `genesis.sh` and `docker-compose.yml` stand up on a box.
- "Connect to a Boltrig instance by URL" needs only the existing `/v1` API and works for the
  hosted service, for a self-hosted single box, and for a dev preview. That is what was built.

Will's reply when shown this (2026-08-22): he had understood the Tauri app to be the entire
Boltrig stack downloaded onto the user's computer, the user's computer becoming the server. It is
not that today. If that is the intended product, the desktop needs, in addition to the phone
pairing layer above: the kernel and fleet worker packaged as sidecars or a bundled runtime,
embedded stand-ins for Postgres, Redis and Hatchet or those services bundled, all state on the
user's disk, the optional local model, a first-run flow replacing `genesis.sh`, and auto-update
that is allowed wherever the desktop is distributed. That is a separate program and a product
decision; it is recorded here as Will's intent signal, not as a decision taken.

The decision taken on the branch, swappable: the phone targets an instance URL (hosted by
default, changeable on the sign-in screen, https only, token scoped to the instance). This keeps
Will's "not the site, my own box" direction open without inventing a desktop server. If the
product later ships a desktop that IS the server, the phone needs only a pairing flow that hands
it the URL and a first token; the rest of the client is unchanged. Until then, a self-hosted
single box (`genesis.sh` on any machine that runs Docker) is already a valid target of this app. Shipping "only Tauri plus
iPhone" is a business decision about dropping the hosted web app and is recorded as open; the
code does not prevent it but also does not make the desktop a server.

## What is in the app now

Today (approvals with Approve and Not now, Working now from the server flag, Earlier, pull to
refresh, visible load errors), Chat (streamed turn with live text, queued turns, stop, a
"needs a decision" notice when a HITL or question event arrives, preview workspace only in
debug builds), Settings (real account, companion name, instance, version, legal links, sign out;
section rows are honest "open on the web" links rather than placeholder values), the full
sign-in ceremony above, the brand app icon rendered from `assets/brand/boltrig-app-icon.svg`,
a privacy manifest, `ITSAppUsesNonExemptEncryption = NO`, iPhone only, portrait, iOS 17+.

## What is not, in the order the next owner should do it

1. Native onboarding (six steps, companion choice, provider keys through `PUT /v1/ai-keys`).
   Until then the app tells a not-yet-onboarded account to finish on the web.
2. Full chat event rendering: tool receipts, display objects, artifacts, subagents, questions
   inline, reconnect via `GET /v1/conversations/{id}/events?follow=1&since=`, history via
   `GET /v1/conversations/{id}`, attachments, model choice.
3. Settings parity through the server-backed settings registry.
4. Push notifications for approvals (needs an APNs token contract on the server; none exists),
   universal links for invitation and reset emails (needs
   `/.well-known/apple-app-site-association`, which today soft-404s the marketing home page).
5. Account deletion in the app (needs a server route; none exists) and the legal pages it links
   to. See `docs/IOS-LAUNCH-READINESS.md`.

## Web defects from Part 1, status

Confirmed on main and left as recorded, not fixed on this branch: `ReadyStep.tsx` names every
non-Jarvis companion "Familiar" (`apps/worker/src/components/onboarding/ReadyStep.tsx`),
`OnboardingGate.tsx` drops a stored Ultron or Colossus back to Familiar
(`apps/worker/src/components/onboarding/OnboardingGate.tsx`), `MobileToday` infers Working now,
caps at twelve and swallows load failures, and has no focused test. They are small and should
travel as their own worker PR with red-first tests.

## Test ledger

`xcodebuild ... build` on the M4 simulator (Xcode 26.6, iPhone 17 simulator): succeeded on the
first compile of the restructured project after one project-file fix (Info.plist inside a
synchronized folder must be excluded from resources). `xcodebuild ... test`: 21 tests executed,
21 passed, 0 failures, on a signed simulator build. The first run found three real defects that
the fixes on this branch closed: 401s on the sign-in routes were collapsed to generic "sign in"
copy instead of the server's reason, `AsyncBytes.lines` does not deliver the blank lines that
delimit SSE frames (the chat stream is now split by hand), and the Keychain test needs a signed
host (an unsigned `CODE_SIGNING_ALLOWED=NO` build fails it with errSecMissingEntitlement; the
test now skips with that message instead of failing). The suites are
`ios/BoltrigTests/SessionStoreTests.swift` (sign-in ceremony, clamps, restore, sign-out, instance
change) and `ios/BoltrigTests/ClientAndParsingTests.swift` (instance parsing, error envelopes,
sign-in decoding, account decoding, SSE framing, event mapping, streamed and queued chat,
conversation and approval decoding, Keychain round trip). All run against an in-memory
URLProtocol stub, no network.


---

# Part 3: the Familiar-only plan, and what landed the same day (2026-08-22, later)

Will decided the iPhone ships **only Familiar**; the approved plan lives in the session record
and is summarised here with what shipped on `feat/ios-app`:

- **S1 Familiar only**: the bundle names no other companion; an account whose companion is
  unset or another character is switched to Familiar the first time the phone loads it
  (`PUT /v1/me/settings {"agent.character":"familiar"}`, then `POST /v1/familiar/emotion/adopted`,
  re-read, one plain notice; retried next launch on failure). Will chose "always switch".
- **S2 the Familiar island**: `apps/worker/familiar-island/` builds the vendored shader plus its
  host logic into one self-contained html (163 KB, CSP-hash pinned, byte deterministic),
  synced into `ios/Boltrig/Resources/FamiliarIsland/` with a manifest; `make familiar-island`
  rebuilds, `make familiar-island-check` guards staleness inside `worker-quality`.
- **S3 presence**: `ios/Boltrig/Familiar/` holds the bridge (state in, reports out), the one
  web view controller (claim per surface, 30 Hz coalescing, file-only navigation, badge fallback,
  unified-log reports), a SwiftUI port of the SVG badge with the genotype rules, and the
  presence on Chat (hero when empty, conversation above the thread) and Today (header).
  Evidence: `docs/design/evidence/2026-08-ios-familiar/`.
- **S4 chat completeness**: `ChatSession` owns history (`GET /v1/conversations/{id}`), the
  follow stream with cursors (409 idle is quiet), stop (cooperative cancel), inline questions,
  receipts, attachment limits from `/v1/chat/config`. A stale `active_run_id` cannot loop.
- **S4b the linked computer** (Will's change: "the iPhone is a remote link to the DMG"): Today
  and Settings show the computers signed in with Boltrig Desktop (`GET /v1/devices`), a
  download link, and Disconnect (`DELETE /v1/devices/{id}`).

Measured: 43 XCTest cases pass on the iPhone 17 simulator; worker suites for the island 41
pass; `make worker-quality` gates (typecheck, structure, build, island check) pass; the
additive evidence receipt was re-captured for the renderer edit.

## The desktop link, precisely

What the repository says about "the phone as a remote for the desktop" (read 2026-08-22):

- Boltrig Desktop enrols itself automatically after signing in with the account; there is no
  pairing code anywhere (`docs/decisions/0027-browser-cloud-desktop-local-agent.md`). The
  natural link is "same account". The phone therefore links by signing in, and sees the desktop
  in `GET /v1/devices` (label, presence, `last_seen_at` refreshed every 3 s while the desktop
  runs, roots).
- A chat turn never runs on the desktop: decision 0027 makes it a surface boundary with no
  fallback (`boltrig/fleet` has no device reference). Desktop work is reached only through the
  `device.*` verbs with an explicit device and root, behind an approval that a DIFFERENT person
  must give (`boltrig/device_leases.py` offers no sole-author relief), so a single-human tenant
  cannot materialise a device lease from any surface today. Command output is never returned,
  only exit codes and digests.
- The DMG lives on GitHub Releases; the web app's download link is a build-time constant, and
  no kernel route publishes it. The phone points at the releases page for now.

So the phone IS a remote for the account the desktop is signed in to (see it, approve for it,
disconnect it) and is NOT yet a remote control of work on that computer.

**Will's direction (2026-08-22, later):** "the phone is a proxy for the desktop. Maybe it needs
a device lease, but the permissions should be exactly the same, and the phone is just an
extension of the monitor remotely." Recorded as the proposed decision
`docs/decisions/0040-phone-as-remote-monitor-of-the-desktop.md`: a phone-originated task on a
linked desktop is a local task in 0027's sense, under the desktop's own device-side posture,
admitted by a signed remote-session lease that needs no independent approver (the
`device.command.run` rule is untouched), with approvals and receipts mirrored to the phone and
typed absence when the computer is off. The record lists what it needs, in order; none of it is
built yet.

## What landed after Part 3 (S5 to S9, the same day, later still)

All on `feat/ios-app`, each slice one commit, each verified by the full XCTest suite on the
iPhone 17 simulator (Xcode 26.6, M4). The ledger now reads **94 tests, 94 passed**.

- **S5 spoken replies** (`ios/Boltrig/Speech/`): `SpeechResolution` mirrors the web rule
  (the `voice.read_replies` setting turns it on; the provider bound to `voice.speak` in
  `GET /v1/capabilities` decides the route; a valid local-voice override or Familiar's own
  bundle voice decides the voice; no voice means silence). `ReplySpeaker` asks the server to
  speak a finished reply once per run (`POST /v1/invoke voice.speak`), plays the audio with
  metering, ducks other audio, stays silent on every failure, and stops when the person moves
  on. Its level drives the presence's speaking mode. The phone's built-in speech is never used.
- **S6 presence budgets** (`FamiliarIslandController`): the phenotype is polled every 3 s only
  while a surface holds the island and the scene is active; backgrounding or releasing hands
  `nil` to the island and Familiar wanders on her own. Measured on the simulator from the
  unified log: page 163,384 bytes; `ready` 1.0 s after the load began (the 500 ms target was
  not met on the simulator; measure on a device before tuning); hero 59 to 60 fps; conversation
  30 fps; 0 frames while another app is in front; 1 fps under Reduce Motion; the WebContent
  process holds 20.6 MB; one phenotype request per 3 s (a test proves the gating).
- **S7 first-run setup** (`ios/Boltrig/Views/Onboarding/`, `OnboardingStore`,
  `ProviderSetupStore`): Name, Connect your AI, an optional image model, Ready with the hero
  presence and the one AI-disclosure line. The provider step keeps the web's one-press rule
  (key blanked before the first await, a pending approval approved in the same press, an
  administrator's pending proposal cached so the next press re-checks and never re-submits, the
  step holds only when the saved provider did not answer, server reasons shown as written).
  Finish writes `PATCH /v1/me/profile`, then `PUT /v1/me/settings` with `agent.character:
  familiar` and `setup.onboarding_version: 1`, then the adopted announcement; a refused name
  returns to the Name step. The provider catalogue is the web's models.dev snapshot bundled
  verbatim (`ios/Boltrig/Resources/ProviderCatalogue.json`, `ios/scripts/sync-provider-catalogue.sh
  --check`, revision pinned by a test, decodes off the main thread in 23 ms).
  `RootDestination.resolve(account)` sends an account without the onboarding version to setup.
- **S8 attachments**: an add button beside the composer offers a photo or a file
  (`AttachmentImporter`): a file is refused by size before its bytes are read; a photo is
  re-encoded as JPEG and shrunk until it fits the per-file limit or refused with the size copy;
  the composer shows one line (the refusal, or the footnote that only text files are read); a
  413 from the chat route reads as plain copy. Limits come from `GET /v1/chat/config`.
- **S9 settings** (`ios/Boltrig/Views/Settings/`, `AccountSettingsStore`,
  `BoltrigClient+Account`): Look (theme, density, text size, reduced motion, high contrast in
  one write with rollback; read out replies), Approvals read-only with the web's three
  descriptions, Archived chats with bring back and an archive action on Today's Earlier rows
  (long press: Today is a scroll of cards, not a list), Security (sessions and keys, this phone
  marked, revoking this phone's key signs out), Spending and Health read-only with plain labels
  (`GET /readyz` tolerates 503), Delete account behind
  `BoltrigEnvironment.accountDeletionAvailable = false` until `DELETE /v1/me` exists.
  Organisation alone still opens on the web. The account's theme now applies on the phone
  (the web default is dark, so an account with no theme key renders dark).

Decisions taken while building, worth a glance: the approval posture is read-only on the phone
because the route refuses a personal access token; a 403 on the provider routes shows the
generic "not allowed" sentence (the flow cannot reach it under the can-add-key gate); a
failed readiness read in setup shows the plain error with Try again rather than the web's
managed-organisation notice.

Not done on the code side: simulator captures of the setup flow (no debug launch argument for
it yet); a live run against `dev.boltrig.ai` with a test account (spoken reply, queued turn,
cancel, the Familiar switch seen in web Settings); push notifications; universal links; the
account-deletion route; crash reporting; live voice calls; a Metal port of the shader.

## What is next, in order

1. The non-code track in `docs/IOS-LAUNCH-READINESS.md` (support and privacy mailbox, legal
   pages at the linked URLs, the App Store Connect record, internal TestFlight on Will's phone,
   the review demo account, error tracking, the `DELETE /v1/me` route). The build and upload
   steps, the App Privacy answers and the review notes are prepared in
   `docs/IOS-TESTFLIGHT-RUNBOOK.md`; only the upload itself needs Will's Apple login.
2. A live run against the hosted instance with a test account whose web choice is another
   character: confirm the switch, a spoken reply with `voice.read_replies` on, a queued turn
   and a cancel, and first-run setup end to end.
3. Decision 0040 (the phone as the desktop's remote monitor): the kernel lease and task
   channel, sole-author relief for that lease kind only, the phone's "Work on {computer}"
   choice and mirrored approvals, a published download address.
4. Measure `ready` and memory on a real iPhone; the simulator numbers above are the floor.

Build and test only on the M4; `ios/README.md` has the commands.
