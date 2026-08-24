---
area: 18 The iOS companion application
id-block: BT-REQ-1800 to BT-REQ-1899
referent commit: 19bcae7fa81663fe8998377c86451ba08fb16e48 (origin/main)
author-agent: brownfield-spec agent, area 18
date: 2026-08-24
---

# SPEC-18: The iOS companion application

## Bound of this reading

`ios/` is 87 files and 9,619 lines of Swift. **Every Swift file was opened and read in
full**, along with `ios/README.md`, `ios/Boltrig/Info.plist`,
`ios/Boltrig/PrivacyInfo.xcprivacy`, `ios/ExportOptions.plist`,
`ios/Boltrig.xcodeproj/project.pbxproj` (470 lines, read in full),
`ios/Boltrig.xcodeproj/xcshareddata/xcschemes/Boltrig.xcscheme`,
`ios/scripts/sync-provider-catalogue.sh`, and the island manifest. Nothing in `ios/` was
sampled: this area is small enough to read exhaustively.

Two artefacts were NOT read line by line, and no claim here rests on their content:
`ios/Boltrig/Resources/ProviderCatalogue.json` (403,955 bytes, a machine-generated
models.dev snapshot, verified only by `cmp` against its source) and
`ios/Boltrig/Resources/FamiliarIsland/familiar-island.html` (163,760 bytes, a build
artefact, verified only by its manifest and by the worker test that pins it). One binary,
`AppIcon-1024.png`, was checked for existence only.

Outside `ios/`, five cross-checks were made against the server tree, each cited where it
appears: that every route the client calls exists, that the approval-posture write really
does refuse the phone's credential class, that the minted token's scope is what the client
implies, that the provider catalogue is byte-identical to the web snapshot, and that no
image build copies `ios/`.

The app is NOT small and it is NOT a stub. It is a complete three-tab product with its own
auth ceremony, its own onboarding, its own streaming transport, its own speech path, and a
95-method test suite. This spec is proportionate to that.

---

## 2. Purpose

Boltrig for iPhone is a native SwiftUI client that signs one person in to one Boltrig
instance, runs first-run setup, shows what needs them and what is working, streams a
governed chat turn with Familiar's presence, and reads finished replies aloud in her voice
([`ios/README.md:3`](../../../ios/README.md) `"Native SwiftUI client for Boltrig, Familiar only."`).
It holds exactly one secret, a per-phone personal access token in the Keychain, and every
request it makes is a call the web app already makes against the same `/v1` surface. It is
a second surface onto the hosted kernel, not a second implementation of Boltrig: no
business rule is decided on the phone that the server does not also decide.

## 3. Boundaries

**What it owns.** The whole of `ios/`: one application target (`Boltrig`) and one unit-test
target (`BoltrigTests`), plus `ios/scripts/sync-provider-catalogue.sh`. It owns the client
half of two contracts that live on both sides of a wire: the `/v1` HTTP surface (owned by
the kernel) and the v1 island message contract (owned by `apps/worker/familiar-island/`).

**What it must not touch.** It ships no server code and is copied into no container image.
The three image build files copy only `deploy/`, `boltrig/`, `scripts/`, `sdks/web`,
`apps/worker/{src,public,package.json}` and three token CSS files
([`deploy/kernel.Dockerfile:158`](../../../deploy/kernel.Dockerfile) `"COPY boltrig/ /app/boltrig/"`;
[`deploy/fleet.Dockerfile:63`](../../../deploy/fleet.Dockerfile) `"COPY boltrig/ /app/boltrig/"`;
[`apps/worker/Dockerfile:21`](../../../apps/worker/Dockerfile) `"COPY apps/worker/src ./apps/worker/src"`).
No `COPY` names `ios/` (bounded: `grep -n 'COPY' deploy/*.Dockerfile apps/worker/Dockerfile
services/channel_gateway/Dockerfile services/channel_gateway/whatsapp_bridge/Dockerfile`,
2026-08-24, pinned tree). A kernel or web roll therefore never ships the phone app;
distribution is TestFlight and the App Store only.

**Forbidden imports, and by what rule.** There is no lint rule and no structure gate on the
Swift tree (bounded: `rg -n -i 'xcodebuild|ios|swift' .github/` returns nothing; `rg -n
'ios' .dockerignore` returns nothing; the Makefile's only `ios`-touching targets are
`familiar-island` and `familiar-island-check`, [`Makefile:248`](../../../Makefile)
`"familiar-island: ## Build the Familiar island page and copy it into the iOS app bundle"`).
The boundaries below are conventions the code holds, not rules a gate enforces:

- The app depends on no third-party package. `packageProductDependencies = ()` on both
  targets ([`ios/Boltrig.xcodeproj/project.pbxproj:105`](../../../ios/Boltrig.xcodeproj/project.pbxproj)
  `"packageProductDependencies = ("`) and both `Frameworks` build phases have empty `files`
  ([`ios/Boltrig.xcodeproj/project.pbxproj:54`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"files = ("`).
  Every import is an Apple SDK framework.
- Only `SessionStore` reads or writes the Keychain, through `KeychainSessionVault`
  ([`ios/Boltrig/Session/SessionVault.swift:11`](../../../ios/Boltrig/Session/SessionVault.swift)
  `"struct KeychainSessionVault: SessionVault {"`). No other type calls `Keychain`
  (bounded: `rg -n 'Keychain\.' ios/`, 2026-08-24, pinned tree, matches only
  `ios/Boltrig/Session/SessionVault.swift`, `ios/BoltrigTests/ClientAndParsingTests.swift`
  and `ios/README.md`; the calls inside `Support/Keychain.swift` itself are unqualified).
- Only `BoltrigClient` and its five extensions build a `URLRequest`. Views never call the
  network; they call a store.
- The stored companion id is never rendered. `CompanionPresence` reduces it to three cases
  and the id itself is dropped ([`ios/Boltrig/Models/CompanionPresence.swift:5`](../../../ios/Boltrig/Models/CompanionPresence.swift)
  `"The stored id itself is never displayed."`). The bundle names no other companion, and
  a worker test asserts it of the island page
  ([`apps/worker/tests/familiarIsland.test.ts:415`](../../../apps/worker/tests/familiarIsland.test.ts)
  `"for (const name of [\"jarvis\", \"ultron\", \"colossus\"])"`).
- Debug-only surfaces are fenced by `#if DEBUG`: the preview workspace
  ([`ios/Boltrig/App/BoltrigApp.swift:35`](../../../ios/Boltrig/App/BoltrigApp.swift) `"#if DEBUG"`)
  and the whole stub server ([`ios/Boltrig/Support/SetupPreview.swift:3`](../../../ios/Boltrig/Support/SetupPreview.swift)
  `"#if DEBUG"`). Nothing in `SetupPreview.swift` compiles into a Release build.

**The seam.** Everything the app shows comes from the kernel over HTTPS. The app supplies no
model, no queue, no persistence beyond one credential, and no offline copy of the record.

## 4. Objects and contracts

### 4.1 Session and credential

| Type | Where | Shape and lifecycle |
| --- | --- | --- |
| `StoredSession` | [`ios/Boltrig/Models/AuthModels.swift:145`](../../../ios/Boltrig/Models/AuthModels.swift) `"struct StoredSession: Codable, Equatable {"` | `instanceURL`, `tokenID`, `secret`, `createdAt`. The whole persisted state of a signed-in phone. Written once at the end of the sign-in ceremony, read at every launch, deleted on sign-out, on instance change, and on a 401 or 403 at restore. |
| `SessionStore.State` | [`ios/Boltrig/Session/SessionStore.swift:14`](../../../ios/Boltrig/Session/SessionStore.swift) `"enum State: Equatable {"` | Nine cases: `restoring`, `signedOut`, `signingIn`, `twoFactor(challengeToken:)`, `passwordChange(csrfToken:)`, `twoFactorEnrolment(csrfToken:enrolment:)`, `recoveryCodes(csrfToken:codes:)`, `unreachable`, `signedIn(Account)`. The root view renders from this alone. |
| `Authorization` | [`ios/Boltrig/Networking/BoltrigClient.swift:4`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"enum Authorization: Equatable {"` | `.none` (sign-in and recovery), `.session(csrfToken:)` (cookie ceremony), `.accessToken(String)` (everything after). One client, one authorization, one URLSession. |
| `Account` | [`ios/Boltrig/Models/AuthModels.swift:41`](../../../ios/Boltrig/Models/AuthModels.swift) `"struct Account: Equatable {"` | `id`, `email`, `displayName`, `role`, `activeWorkspaceID`, `onboardingComplete`, `characterID`, `readReplies`, `voiceOverrides`, `appearance`, and the raw `settings` bag. `==` deliberately excludes `settings` ([`:77`](../../../ios/Boltrig/Models/AuthModels.swift) `"static func == (lhs: Account, rhs: Account) -> Bool {"`). |
| `AppearanceSettings` | [`ios/Boltrig/Models/AuthModels.swift:154`](../../../ios/Boltrig/Models/AuthModels.swift) `"struct AppearanceSettings: Equatable {"` | `theme` (default `.dark`), `density`, `fontScale` (one of `0.9 1 1.1 1.25`), `reducedMotion`, `highContrast`. `wireForm` is the five keys the web writes together. |
| `CompanionPresence` | [`ios/Boltrig/Models/CompanionPresence.swift:6`](../../../ios/Boltrig/Models/CompanionPresence.swift) `"enum CompanionPresence: Equatable {"` | `.familiar`, `.unset`, `.other`. `needsAdoption` is `self != .familiar`. |

`Account.decode` is hand-written over `JSONSerialization` because the settings bag mixes
strings, numbers and booleans ([`ios/Boltrig/Models/AuthModels.swift:102`](../../../ios/Boltrig/Models/AuthModels.swift)
`"static func decode(_ data: Data) throws -> Account {"`). `onboardingComplete` is
`setup.onboarding_version >= 1`, read tolerantly from `Int`, `Double` or `String`
([`:110`](../../../ios/Boltrig/Models/AuthModels.swift) `"let onboardingVersion: Int = {"`).
Booleans accept `true`, `1`, `"true"`, `"1"`, `"yes"`, `"on"`
([`:138`](../../../ios/Boltrig/Models/AuthModels.swift) `"[\"true\", \"1\", \"yes\", \"on\"].contains"`).

### 4.2 Work objects

| Type | Where | Notes |
| --- | --- | --- |
| `ConversationSummary` | [`ios/Boltrig/Models/AppModels.swift:11`](../../../ios/Boltrig/Models/AppModels.swift) `"struct ConversationSummary: Identifiable, Codable, Hashable {"` | `working` is the server's own flag; `isWorking` is `working ?? false` and is never inferred ([`:9`](../../../ios/Boltrig/Models/AppModels.swift) `"the server's own answer to"`). |
| `ApprovalRequest` | [`ios/Boltrig/Models/AppModels.swift:33`](../../../ios/Boltrig/Models/AppModels.swift) `"struct ApprovalRequest: Identifiable, Codable, Hashable {"` | `heading` prefers the verb, else a phrase per `type`. |
| `StoredMessage` | [`ios/Boltrig/Models/ChatHistoryModels.swift:4`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"struct StoredMessage: Identifiable, Equatable {"` | Roles collapse to `user`, `assistant`, `other`. Carries `runID`, `hitlRequestID`, `attachments`, `supersededBy`. |
| `ConversationHistory` | [`ios/Boltrig/Models/ChatHistoryModels.swift:47`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"struct ConversationHistory: Equatable {"` | `activeRunID` is the only liveness signal the app trusts. |
| `ChatAttachment` | [`ios/Boltrig/Models/ChatHistoryModels.swift:73`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"struct ChatAttachment: Equatable {"` | `wireForm` is `{name, media_type, data}` with `data` base64. |
| `AttachmentLimits` | [`ios/Boltrig/Models/ChatHistoryModels.swift:85`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"struct AttachmentLimits: Equatable {"` | Code defaults 8 files, 256 KiB each, 1 MiB total. A deployment can only tighten them. |
| `LinkedDevice` | [`ios/Boltrig/Models/LinkedDevice.swift:6`](../../../ios/Boltrig/Models/LinkedDevice.swift) `"struct LinkedDevice: Identifiable, Equatable {"` | Liveness is `presence == "online"` AND `last_seen_at` within 20 s, because the server never marks a device offline ([`:14`](../../../ios/Boltrig/Models/LinkedDevice.swift) `"static let liveWindow: TimeInterval = 20"`). |
| `UserSession`, `AccessTokenView`, `BudgetView`, `CostSummary`, `ReadinessReport`, `ApprovalPostureReading` | [`ios/Boltrig/Models/AccountModels.swift`](../../../ios/Boltrig/Models/AccountModels.swift) | Read-only account records. `ReadinessReport.labels` maps nine probe ids to plain words ([`:225`](../../../ios/Boltrig/Models/AccountModels.swift) `"static let labels: [String: String] = ["`). |

### 4.3 The chat stream vocabulary

`ChatEvent` names twenty-two cases and maps twenty-one wire `type` values, with everything
else becoming `.other(type:)` ([`ios/Boltrig/Networking/ChatEvent.swift:6`](../../../ios/Boltrig/Networking/ChatEvent.swift)
`"enum ChatEvent: Equatable {"`; [`:88`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"return .other(type: type)"`).
The declared reason is that the server's vocabulary may grow before the app does
([`:33`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"rather than failing the turn"`).
The mapped types are `message_start`, `text_delta`, `reasoning_delta`, `tool_call`,
`tool_result`, `subagent`, `subagent_end`, `steer_queued`, `steer_consumed`, `hitl`,
`question`, `heartbeat`, `message_end`, `cancelled`, `artifact`, `artifact_rejected`,
`model_routing`, `workflow_step`, `workflow_run`, `display_object`, `event_unavailable`.
`.queued` has no wire type: it is synthesised from a 202.

`SSEFrameParser` is a two-method state machine: `consume(line:)` collects `data:` payloads
and returns a frame on the first empty line, `flush()` closes a stream that ended without
one ([`ios/Boltrig/Networking/ChatEvent.swift:100`](../../../ios/Boltrig/Networking/ChatEvent.swift)
`"mutating func consume(line: String) -> [String: Any]? {"`). A frame that is not JSON
becomes the synthetic `{"type": "malformed_event"}` rather than an error
([`:120`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"return [\"type\": \"malformed_event\"]"`),
which `ChatEvent.from` then turns into `.other(type: "malformed_event")`.

### 4.4 The Familiar island contract (v1)

`FamiliarIslandState` is the whole message the phone may send
([`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:6`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift)
`"struct FamiliarIslandState: Codable, Equatable {"`): `v` (always 1), `mode` (six closed
values), `level`, `bands` (exactly eight or dropped), `onset`, `presentation`
(`hero|conversation|minimised`), `reducedMotion`, `appearance`, `dprCap`, `phenotype`,
`genotype`. The contract is explicit that nothing here carries text, identifiers or secrets
([`:4`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift)
`"Closed enums and bounded numbers only"`). `clamped()` forces `level`, `onset`, every band
and every phenotype value into `[0,1]` and `dprCap` into `[1,2]`
([`:32`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"func clamped() -> FamiliarIslandState {"`),
and `json()` sorts keys so two equal states encode identically
([`:49`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"encoder.outputFormatting = [.sortedKeys]"`).

The island replies with four report types plus `unknown`
([`:62`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"enum FamiliarIslandReport: Equatable {"`):
`ready(renderer:fragSha256:)`, `fallback(reason:)`, `frame(fps:frameMs:)`, `error(message:)`.

`FamiliarModeResolver.mode` fixes the precedence error > speaking > listening > working >
thinking > standby ([`:97`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift)
`"static func mode(failed: Bool, speaking: Bool"`), stated to mirror the web's
`familiarStateFromTurn`.

### 4.5 Provider catalogue

`ProviderCatalogue` decodes the bundled models.dev snapshot and carries three rule tables:
`bifrostSupported` (23 native provider ids), `catalogueAliases` (6 spelling fixes), and the
synthetic self-hosted Ollama entry inserted immediately before `ollama-cloud`
([`ios/Boltrig/Models/ProviderCatalogue.swift:35`](../../../ios/Boltrig/Models/ProviderCatalogue.swift)
`"static let selfHostedOllama = CatalogueProvider("`; [`:142`](../../../ios/Boltrig/Models/ProviderCatalogue.swift)
`"if id == \"ollama-cloud\" {"`). `needsBaseURL(_:)` is true for a self-hosted entry, and
for any non-native provider the catalogue publishes no `api` for
([`:184`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"func needsBaseURL(_ id: String) -> Bool {"`).
`exactModelID(provider:model:)` prefixes `provider/` unless the provider is `custom` or the
model already carries it ([`:170`](../../../ios/Boltrig/Models/ProviderCatalogue.swift)
`"static func exactModelID(provider: String, model: String) -> String {"`).

---

## 5. Control flow

### 5.1 Launch and restore

1. `BoltrigApp` builds two long-lived objects, `SessionStore` and `FamiliarIslandController`,
   and injects both into the environment
   ([`ios/Boltrig/App/BoltrigApp.swift:5`](../../../ios/Boltrig/App/BoltrigApp.swift)
   `"@StateObject private var session = SessionStore()"`).
2. `RootView.task` calls `await session.restore()`
   ([`ios/Boltrig/App/BoltrigApp.swift:82`](../../../ios/Boltrig/App/BoltrigApp.swift)
   `"await session.restore()"`), unless a debug launch argument diverts to a preview
   (5.9 below).
3. `restore()` loads the vault. **No stored session**: state becomes `.signedOut`
   ([`ios/Boltrig/Session/SessionStore.swift:71`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"guard let stored = try? vault.load() else {"`).
4. **Stored session for a different instance**: the vault is cleared and state becomes
   `.signedOut` with no network call at all
   ([`:75`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard stored.instanceURL == instanceURL else {"`).
   Proven by `BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken`,
   which asserts `StubURLProtocol.requests.isEmpty`.
5. Otherwise `GET /v1/me/settings` is called with the stored token
   ([`:82`](../../../ios/Boltrig/Session/SessionStore.swift) `"let account = try await tokenClient(stored.secret).account()"`).
   **Failure branch, and it is three-way**:
   `.unauthenticated` or `.forbidden` clears the vault and signs out;
   `.unreachable` or `.server` keeps the token and shows the unreachable screen;
   anything else clears the vault, signs out and shows the error
   ([`:85`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .unauthenticated, .forbidden:"`).
   A non-`BoltrigError` throw is treated as unreachable ([`:96`](../../../ios/Boltrig/Session/SessionStore.swift) `"state = .unreachable"`).
6. On success the account passes through `adoptFamiliarIfNeeded` (5.3) before the state
   becomes `.signedIn`.
7. `RootView.sessionDriven` renders: `.restoring` gives `LaunchView`, `.unreachable` gives
   `UnreachableView` with Try again and Sign in again, `.signedIn` branches on
   `RootDestination.resolve`, and every other case gives `AuthFlowView`
   ([`ios/Boltrig/App/BoltrigApp.swift:88`](../../../ios/Boltrig/App/BoltrigApp.swift) `"switch session.state {"`).
   The comment states the rule: nothing private renders until the server has confirmed who
   is signed in ([`:29`](../../../ios/Boltrig/App/BoltrigApp.swift) `"Nothing private renders"`).
8. `RootDestination.resolve(account)` is one line: `onboardingComplete ? .workspace :
   .onboarding` ([`:24`](../../../ios/Boltrig/App/BoltrigApp.swift)
   `"account.onboardingComplete ? .workspace : .onboarding"`).

### 5.2 The sign-in ceremony

1. `signIn(email:password:)` trims the email and refuses an empty field locally before any
   request ([`ios/Boltrig/Session/SessionStore.swift:110`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"guard !trimmedEmail.isEmpty, !password.isEmpty else {"`).
2. A fresh `URLSession` is created and held as `signInSession`; it accepts cookies
   ([`:116`](../../../ios/Boltrig/Session/SessionStore.swift) `"let session = URLSession(configuration: self.configuration)"`).
3. `POST /v1/auth/login {email, password}`
   ([`ios/Boltrig/Networking/BoltrigClient.swift:32`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"perform(path: \"/v1/auth/login\", method: \"POST\", body: body)"`).
   `decodeSignIn` maps exactly four server statuses and throws on anything else
   ([`:230`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"static func decodeSignIn(_ data: Data) throws -> SignInOutcome {"`).
   The server side produces exactly those four
   ([`boltrig/api/auth_routes.py:502`](../../../boltrig/api/auth_routes.py)
   `"return JSONResponse({\"status\": \"2fa_required\", \"challenge_token\": challenge})"`;
   [`:521`](../../../boltrig/api/auth_routes.py) `"clamped = \"password_change_required\" if user.must_change_password else \"ok\""`).
   **Failure branch**: a 401 whose reason is not a session reason becomes
   `.rejected(reason:)` and is shown as the server's own sentence, so "invalid email or
   password" reaches the person instead of a generic "sign in"
   ([`ios/Boltrig/Networking/BoltrigClient.swift:269`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"if let reason, !sessionReasons.contains(reason) {"`).
4. `route(_:)` puts the ceremony into one of four states
   ([`ios/Boltrig/Session/SessionStore.swift:261`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"private func route(_ outcome: SignInOutcome) async {"`):
   - `2fa_required` gives `.twoFactor(challengeToken:)`. **No session exists yet**, proven by
     `SessionStoreTests/testTwoFactorRequiredAsksForTheCodeThenSignsIn` asserting
     `vault.stored` is nil at that point.
   - `password_change_required` gives `.passwordChange(csrfToken:)`.
   - `2fa_enrollment_required` gives `.twoFactorEnrolment(csrfToken:enrolment: nil)`.
   - `ok` goes straight to `finishSignIn`.
5. `submitTwoFactorCode` posts `/v1/auth/2fa/challenge {challenge_token, code}` on the same
   cookie session and re-routes the outcome
   ([`:134`](../../../ios/Boltrig/Session/SessionStore.swift) `"completeTwoFactor(challengeToken: challengeToken, code: trimmed)"`).
   **Failure branch**: a wrong code leaves the state on `.twoFactor` and shows the plain
   copy for `invalid or expired code`.
6. `changePassword` enforces twelve characters and a matching confirmation **before** any
   request ([`:143`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard new.count >= 12 else {"`),
   then `POST /v1/auth/change-password` with the CSRF header, then `finishSignIn`.
   `SessionStoreTests/testForcedPasswordChangeIsCompletedBeforeTheTokenIsMinted` asserts a
   too-short password never leaves the phone.
7. Two-step enrolment is two calls: `beginTwoFactorEnrolment` (`POST /v1/auth/2fa/enroll`)
   returns the otpauth URI, the secret and the recovery codes, and
   `verifyTwoFactorEnrolment` (`POST /v1/auth/2fa/verify-enroll`) activates it and moves to
   `.recoveryCodes`. The server returns those three fields exactly once
   ([`boltrig/api/auth_routes.py:653`](../../../boltrig/api/auth_routes.py) `"recovery_codes": codes,`).
   The codes are held only in the enum case and are never written anywhere
   ([`ios/Boltrig/Models/AuthModels.swift:21`](../../../ios/Boltrig/Models/AuthModels.swift)
   `"shown to the person exactly once and never stored by the app"`).
8. `finishSignIn(csrfToken:)` is the whole point of the ceremony
   ([`ios/Boltrig/Session/SessionStore.swift:276`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"private func finishSignIn(csrfToken: String) async {"`):
   a. `POST /v1/me/tokens {name, ttl_days: 90}` mints the phone's key
      ([`ios/Boltrig/Networking/BoltrigClient.swift:70`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
      `"[\"name\": name, \"ttl_days\": ttlDays]"`). The name is
      `"<device model> app, signed in yyyy-MM-dd"` in `en_US_POSIX`
      ([`ios/Boltrig/Session/SessionStore.swift:343`](../../../ios/Boltrig/Session/SessionStore.swift)
      `"\\(UIDevice.current.model) app, signed in"`).
      A response without a non-empty `secret` throws `invalidResponse`
      ([`ios/Boltrig/Networking/BoltrigClient.swift:73`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
      `"let secret = object[\"secret\"] as? String, !secret.isEmpty else {"`).
   b. `StoredSession` is written to the Keychain.
   c. `POST /v1/auth/logout` closes the cookie session, **best effort**: the call is `try?`
      ([`ios/Boltrig/Session/SessionStore.swift:286`](../../../ios/Boltrig/Session/SessionStore.swift)
      `"try? await sessionClient.logout()"`).
   d. `GET /v1/me/settings` with the new token loads the account, then adoption runs.
   **Failure branch**: a `passwordChangeRequired` or `twoFactorEnrolmentRequired` error
   thrown by the mint call routes back into the ceremony rather than out of it
   ([`:292`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .passwordChangeRequired:"`);
   anything else clears the vault and returns to `.signedOut` with the message.
9. `cancelSignIn()` drops the half-finished session and returns to the form
   ([`:203`](../../../ios/Boltrig/Session/SessionStore.swift) `"func cancelSignIn() {"`).
   Every ceremony screen offers it as "Start again"
   ([`ios/Boltrig/Views/Auth/AuthFlowView.swift:227`](../../../ios/Boltrig/Views/Auth/AuthFlowView.swift)
   `"Button(\"Start again\") { session.cancelSignIn() }"`).

**Password reset** is a fire-and-forget `POST /v1/auth/password-reset/request` whose success
copy is deliberately non-committal, so the screen never reveals whether the account exists
([`ios/Boltrig/Session/SessionStore.swift:198`](../../../ios/Boltrig/Session/SessionStore.swift)
`"If that account can be recovered, reset instructions are on their way"`).

### 5.3 Familiar adoption

1. `adoptFamiliarIfNeeded` returns immediately when the companion is already Familiar
   ([`ios/Boltrig/Session/SessionStore.swift:244`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"guard account.companionPresence.needsAdoption else { return account }"`).
2. Otherwise: `PUT /v1/me/settings {"agent.character":"familiar"}`
   ([`:246`](../../../ios/Boltrig/Session/SessionStore.swift) `"try await client.putSettings([\"agent.character\": CompanionPresence.familiarID])"`),
   then `POST /v1/familiar/emotion/adopted {"character":"familiar"}` as `try?`
   ([`:247`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await client.announceAdopted(character:"`),
   then a single notice, then `GET /v1/me/settings` again to re-read.
3. **Failure branch**: a failed write is reported as "Boltrig could not set Familiar as your
   companion. It will try again next time." and the ORIGINAL account is returned, so the
   person is still signed in ([`:254`](../../../ios/Boltrig/Session/SessionStore.swift)
   `"familiarAdoptedNotice = \"Boltrig could not set Familiar\""`). The announcement never
   fires when the write failed, proven by
   `SessionStoreTests/testFailedAdoptionWriteSaysSoAndStillSignsIn`.
4. Ordering is asserted: `SessionStoreTests/testAnotherCompanionIsSwitchedToFamiliarOnFirstLoad`
   checks that `/v1/familiar/emotion/adopted` appears after `/v1/me/settings` in the
   recorded request sequence.

### 5.4 Today

1. `AppStore.loadIfNeeded` runs once per workspace: refresh, then chat limits, then speech
   resolution ([`ios/Boltrig/Session/AppStore.swift:66`](../../../ios/Boltrig/Session/AppStore.swift)
   `"guard !loadedOnce else { return }"`).
2. `refresh()` fetches `/v1/hitl` and `/v1/conversations` concurrently with `async let`, then
   filters out closed conversations
   ([`:100`](../../../ios/Boltrig/Session/AppStore.swift) `"newConversations.filter { $0.status.lowercased() != \"closed\" }"`).
3. `/v1/devices` is fetched separately with `try?`, so **not knowing which computers are
   linked is not an error** ([`:102`](../../../ios/Boltrig/Session/AppStore.swift)
   `"if let linked = try? await client.devices() { devices ="`).
   Proven by `LinkedDeviceTests/testDevicesFailureLeavesTheRestOfTodayIntact`.
   **Failure branch of the pair**: either of the two required reads failing sets `loadError`,
   which Today renders as a banner ([`ios/Boltrig/Views/TodayView.swift:26`](../../../ios/Boltrig/Views/TodayView.swift)
   `"NoticeBanner(message: loadError, symbol:"`).
4. Sections render in fixed order: header with presence and initials, linked computer line,
   load error, notice, "Needs you", "Working now", "Earlier", then either an empty state or
   a spinner ([`ios/Boltrig/Views/TodayView.swift:32`](../../../ios/Boltrig/Views/TodayView.swift)
   `"if !store.approvals.isEmpty {"`).
5. Approve and Not now call `POST /v1/hitl/{id}/respond {decision, notes:""}`
   ([`ios/Boltrig/Networking/BoltrigClient.swift:116`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"[\"decision\": decision, \"notes\": \"\"]"`) and remove the row only on success
   ([`ios/Boltrig/Session/AppStore.swift:148`](../../../ios/Boltrig/Session/AppStore.swift)
   `"approvals.removeAll { $0.id == approval.id }"`). **Failure branch**: the row stays and
   the error becomes `notice`.
6. A long press on an Earlier row offers Archive, which soft-closes through
   `AccountSettingsStore.archive` and then refreshes Today
   ([`ios/Boltrig/Views/TodayView.swift:220`](../../../ios/Boltrig/Views/TodayView.swift)
   `"private func archive(_ conversation: ConversationSummary) {"`).
7. A turn that ended with something waiting posts `.boltrigNeedsYou`, which Today observes
   and refreshes on ([`ios/Boltrig/Session/AppStore.swift:156`](../../../ios/Boltrig/Session/AppStore.swift)
   `"NotificationCenter.default.addObserver(forName: .boltrigNeedsYou"`).

### 5.5 A chat turn

1. `sendMessage` appends the person's message locally, stops any speech, clears the
   attachment tray, and marks the turn sending
   ([`ios/Boltrig/Session/ChatSession.swift:147`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"func sendMessage(_ value: String) async {"`).
2. `streamChat` posts `/v1/chat` with `message`, `origin: "ios"`, `idempotency_key` (a fresh
   UUID), `attachments`, and `conversation_id` when one is open
   ([`ios/Boltrig/Networking/BoltrigClient.swift:132`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"\"origin\": \"ios\","`), with `Accept: text/event-stream` and a 600 s timeout
   ([`:139`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"request.timeoutInterval = 600"`).
3. **202 branch**: the body is drained, one `.queued(conversationID:)` event is yielded, and
   the stream finishes ([`:144`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"if http.statusCode == 202 {"`). `ChatSession` renders one notice about the queue.
4. **Non-2xx branch**: the body is drained and mapped through `mapError`, thrown into the
   stream ([`:152`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
   `"throw Self.mapError(status: http.statusCode, data: try await SSEByteReader.collect(bytes))"`).
5. **2xx branch**: bytes are read one at a time and split on `\n` by hand, because
   `AsyncBytes.lines` does not deliver the blank lines that end a frame
   ([`ios/Boltrig/Networking/SSEByteReader.swift:3`](../../../ios/Boltrig/Networking/SSEByteReader.swift)
   `"Lines are split by hand because"`). A trailing `\r` is stripped
   ([`:16`](../../../ios/Boltrig/Networking/SSEByteReader.swift) `"if lineBuffer.last == UInt8(ascii: \"\\r\") { lineBuffer.removeLast() }"`).
6. `ChatSession.apply` folds each event into published state
   ([`ios/Boltrig/Session/ChatSession.swift:291`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"private func apply(_ event: ChatEvent) {"`): text deltas append to `liveReply`, a
   `degraded` delta raises a notice, `hitl` sets `needsYouDuringTurn` and appends a receipt,
   `question` opens the inline question card, tool calls, failed tool results, subagents,
   artifacts and rejected artifacts become receipts, and eleven event types are explicitly
   dropped ([`:321`](../../../ios/Boltrig/Session/ChatSession.swift) `"case .messageEnd, .steerConsumed, .reasoningDelta, .heartbeat, .subagentEnd,"`).
7. `finishTurn` commits `liveReply` as an assistant message and calls the turn-ended handler,
   which is where speech starts ([`:327`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"private func finishTurn(reason: String?) {"`). If the reply is empty and a reason was
   given, the reason becomes the assistant message and `turnFailed` is set, which turns
   Familiar's presence to `error`.
8. **Failure branch**: a 413 is replaced by one fixed sentence about attachments
   ([`:181`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"if (error as? BoltrigError)?.status == 413 { copy = Self.attachmentsRejectedCopy }"`).
9. `stopTurn()` cancels the local task, posts `/v1/runs/{id}/cancel` as `try?`, and settles
   the state ([`:231`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"func stopTurn(cancelOnServer: Bool = true) {"`). Opening another conversation calls the
   same method with `cancelOnServer: false`, so switching chats never cancels a run.

### 5.6 History and reconnect

1. `open(_:)` resets everything when the conversation id changes, then loads history
   ([`ios/Boltrig/Session/ChatSession.swift:81`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"if conversationID != conversation.id {"`).
2. `loadHistory` calls `GET /v1/conversations/{id}` and keeps only messages that are neither
   superseded nor of an unknown role
   ([`:125`](../../../ios/Boltrig/Session/ChatSession.swift) `".filter { $0.supersededBy == nil && $0.role != .other }"`).
3. If the server reports an `active_run_id` **and** this is the first load, the run is
   followed from cursor 0 ([`:127`](../../../ios/Boltrig/Session/ChatSession.swift) `"if followActiveRun {"`).
4. `follow` opens `GET /v1/conversations/{id}/events?follow=1&since=N`
   ([`ios/Boltrig/Networking/BoltrigClient+Chat.swift:36`](../../../ios/Boltrig/Networking/BoltrigClient+Chat.swift)
   `"?follow=1&since=\\(max(0, since))\""`). Each frame carries `cursor`, `event` and
   `replay_truncated`; a truncated replay raises one honest notice
   ([`ios/Boltrig/Session/ChatSession.swift:208`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"Earlier live activity is not shown."`).
5. **409 is not an error**: it yields `.idle`, clears `activeRunID` and finishes
   ([`ios/Boltrig/Networking/BoltrigClient+Chat.swift:41`](../../../ios/Boltrig/Networking/BoltrigClient+Chat.swift)
   `"if http.statusCode == 409 {"`).
6. After the follow ends, history is reloaded with `followActiveRun: false`, so a stale
   `active_run_id` cannot resurrect a finished run and loop
   ([`ios/Boltrig/Session/ChatSession.swift:222`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"await loadHistory(followActiveRun: false)"`). Proven by
   `ChatSessionTests/testStaleActiveRunWithAnIdleFollowDoesNotLoop`, which asserts exactly
   one events call and exactly two history calls.
7. Returning to the foreground calls `reconnectIfRunning`, which is a no-op unless a run is
   known live and nothing else is in flight
   ([`:225`](../../../ios/Boltrig/Session/ChatSession.swift) `"guard activeRunID != nil, !isSending, !isReconnecting else { return }"`;
   [`ios/Boltrig/Views/ChatView.swift:37`](../../../ios/Boltrig/Views/ChatView.swift)
   `"if phase == .active { Task { await chat.reconnectIfRunning() } }"`).

### 5.7 Attachments

1. The plus button offers a photo or a file
   ([`ios/Boltrig/Views/ChatView.swift:172`](../../../ios/Boltrig/Views/ChatView.swift)
   `".confirmationDialog(\"Add to this message\""`).
2. A file is size-checked from `resourceValues` **before its bytes are read**, so a large
   file never fills memory on the way to a refusal
   ([`ios/Boltrig/Support/AttachmentImporter.swift:17`](../../../ios/Boltrig/Support/AttachmentImporter.swift)
   `"let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max"`),
   and re-checked after reading.
3. A photo is re-encoded as JPEG at quality 0.82, 0.6, 0.4, then shrunk by 0.7 on the long
   side, up to ten times, stopping at 160 px
   ([`:33`](../../../ios/Boltrig/Support/AttachmentImporter.swift) `"static func jpeg(_ image: UIImage, under limit: Int) -> Data? {"`).
   **Failure branch**: below 160 px it returns nil and the outcome is the size refusal.
4. `ChatSession.addAttachment` applies three limits in order: count, per-file size, total
   size ([`ios/Boltrig/Session/ChatSession.swift:258`](../../../ios/Boltrig/Session/ChatSession.swift)
   `"if attachments.count >= limits.maxCount {"`), each with its own sentence.
5. Limits come from `GET /v1/chat/config`, falling back to the code defaults when the route
   cannot be read ([`ios/Boltrig/Models/ChatHistoryModels.swift:91`](../../../ios/Boltrig/Models/ChatHistoryModels.swift)
   `"static func decode(_ data: Data) -> AttachmentLimits {"`).

### 5.8 Speech

1. `SpeechResolution.resolve` reads three things: the account's `voice.read_replies`, the
   adapter bound to the `voice.speak` verb in `GET /v1/capabilities`, and either the
   person's local-provider override or Familiar's bundled voice
   ([`ios/Boltrig/Speech/SpeechResolution.swift:26`](../../../ios/Boltrig/Speech/SpeechResolution.swift)
   `"static func resolve(account: Account, capabilities: CapabilitiesSnapshot?)"`).
   An override applies only to `pocket-voice` and only if it matches
   `^[a-z0-9][a-z0-9._-]{0,63}$` ([`:39`](../../../ios/Boltrig/Speech/SpeechResolution.swift)
   `"static func isValidVoiceID(_ value: String) -> Bool {"`).
2. **No voice means silence**: `canSpeak` requires all three
   ([`:24`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"var canSpeak: Bool { enabled && provider != nil && voiceID != nil }"`).
   Nothing invents a default voice, and the phone's own on-device speech synthesiser is
   never used (bounded: `rg -n 'AVSpeechSynthesizer|AVSpeechUtterance' ios/` returns
   nothing, 2026-08-24, pinned tree).
3. `speak(runID:markdown:)` refuses a repeat for a run it has already spoken
   ([`ios/Boltrig/Speech/ReplySpeaker.swift:43`](../../../ios/Boltrig/Speech/ReplySpeaker.swift)
   `"guard !spokenRuns.contains(runID) else { return }"`), reduces the markdown, and calls
   `POST /v1/invoke {noun:"voice", verb:"voice.speak", params:{text, voice}}`.
4. The answer is accepted only if it is `ok`, carries `audio_b64` no longer than 12,000,000
   characters, and declares an `audio/*` content type
   ([`:53`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"encoded.count <= Self.maxAudioBase64"`).
5. **Every failure is silent by design**: the catch block is empty with a stated reason
   ([`:60`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"// Silent by design: no audio is not an error"`).
   A reply that cannot be spoken is still on the screen.
6. Playback uses `.playback` / `.spokenAudio` with `.duckOthers`, and the session is
   deactivated with `notifyOthersOnDeactivation` when it ends
   ([`:113`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"try session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])"`).
7. A generation counter makes a late answer from a superseded request a no-op
   ([`:51`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"guard mine == generation else { return }"`).
8. `AppStore.wireSpeech` binds the finished-turn handler and mirrors `isSpeaking` and `level`
   into the chat session, which is what drives the presence
   ([`ios/Boltrig/Session/AppStore.swift:80`](../../../ios/Boltrig/Session/AppStore.swift)
   `"private func wireSpeech() {"`).

### 5.9 Familiar's presence

1. A surface calls `island.claim(surface)` on appear; only one surface holds the island at a
   time, and the first claim is what creates the web view
   ([`ios/Boltrig/Familiar/FamiliarIslandController.swift:39`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"func claim(_ surface: String) -> Bool {"`). Three surfaces exist: `today`, `chat`,
   `onboarding` (bounded: `rg -n 'FamiliarPresenceView\(surface:' ios/`, 2026-08-24, pinned
   tree, gives exactly four call sites:
   [`ios/Boltrig/Views/TodayView.swift:84`](../../../ios/Boltrig/Views/TodayView.swift)
   `"FamiliarPresenceView(surface: \"today\", presentation: .conversation,"`,
   [`ios/Boltrig/Views/ChatView.swift:92`](../../../ios/Boltrig/Views/ChatView.swift)
   `"FamiliarPresenceView(surface: \"chat\", presentation: .hero,"`,
   [`ios/Boltrig/Views/ChatView.swift:98`](../../../ios/Boltrig/Views/ChatView.swift)
   `"FamiliarPresenceView(surface: \"chat\", presentation: .conversation,"`, and
   [`ios/Boltrig/Views/Onboarding/ReadyStepView.swift:12`](../../../ios/Boltrig/Views/Onboarding/ReadyStepView.swift)
   `"FamiliarPresenceView(surface: \"onboarding\", presentation: .hero,"`).
2. The web view loads `familiar-island.html` from the bundle
   ([`:123`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"if let url = Bundle.main.url(forResource: \"familiar-island\", withExtension: \"html\")"`).
   **Failure branch**: a missing page sets `isAvailable = false` and the badge is used
   forever ([`:128`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"isAvailable = false"`).
3. State is queued and flushed at most 30 times a second, and only after the island has
   reported ready ([`:32`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"private static let sendInterval: TimeInterval = 1.0 / 30.0"`;
   [`:88`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"guard isReady, !flushScheduled else { return }"`).
   An identical JSON is not re-sent ([`:100`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"guard let json = try? state.json(), json != lastSentJSON else { return }"`).
4. Reports come back over one named message handler held weakly
   ([`:198`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"private final class WeakScriptMessageHandler: NSObject, WKScriptMessageHandler {"`) and
   are logged to the `ai.boltrig.app` subsystem
   ([`:35`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"Logger(subsystem: \"ai.boltrig.app\", category: \"familiar-island\")"`).
   A `fallback` report or any navigation failure sets `isFallback`, which the presence view
   reads as "show the badge".
5. A dead web content process is reloaded and `isReady` is dropped
   ([`:188`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {"`).
6. The phenotype poll runs every 3 s and only while a surface holds the island AND the scene
   is active ([`:70`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
   `"guard let client = phenotypeSource, owner != nil, sceneActive else {"`). Backgrounding
   or releasing hands `nil` to the island, and she wanders on her own. Proven by
   `PhenotypeTests/testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive`.
7. `FamiliarPresenceView` attaches the web view as soon as the surface holds it, but fades it
   in only when ready, and shows the badge until then, so nothing is ever blank
   ([`ios/Boltrig/Familiar/FamiliarPresenceView.swift:21`](../../../ios/Boltrig/Familiar/FamiliarPresenceView.swift)
   `"private var hostsIsland: Bool {"`).
8. `push()` sends mode, level, presentation (forced to `minimised` when the scene is not
   active), reduced motion, appearance, and a dpr cap of at most 2
   ([`:65`](../../../ios/Boltrig/Familiar/FamiliarPresenceView.swift) `"private func push() {"`).

### 5.10 First-run setup

1. `OnboardingStore` has four steps: `name`, `provider`, `vision`, `ready`
   ([`ios/Boltrig/Session/OnboardingStore.swift:10`](../../../ios/Boltrig/Session/OnboardingStore.swift)
   `"case name, provider, vision, ready"`). There is no companion step and no voice step,
   because the phone ships only Familiar.
2. An account that already has a display name starts at `provider`
   ([`:65`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"account.displayName.isEmpty ? .name : .provider"`).
3. The Name step normalises locally before sending: whitespace collapsed, 1 to 80 scalars,
   no control, format or surrogate characters
   ([`:167`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"static func normalizedName(_ raw: String) -> String? {"`).
4. The Provider step runs `ProviderSetupStore.complete()` and advances only on true.
   The Image model step does the same, and then finishes.
   Skip finishes without submitting anything
   ([`:120`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"func skipVision() async {"`).
5. `finish()` is guarded against a second press while the first is in flight
   ([`:129`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"guard !finishInFlight else { return false }"`)
   and writes in a fixed order: `PATCH /v1/me/profile`, then
   `PUT /v1/me/settings {agent.character: familiar, setup.onboarding_version: 1}`, then the
   adopted announcement as `try?` ([`:143`](../../../ios/Boltrig/Session/OnboardingStore.swift)
   `"try await client.updateProfile(displayName: displayName)"`).
   Proven by `OnboardingTests/testFinishWritesProfileThenSettingsOnceUnderConcurrentPresses`,
   which fires two `finish()` calls concurrently and asserts exactly one PATCH, one PUT, and
   `PATCH` before `PUT`.
6. **Failure branch**: a refused display name (`display_name must be 1-80 safe characters`)
   sends the person back to the Name step with the plain sentence
   ([`:149`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"reason == BoltrigError.displayNameReason"`);
   anything else stays on the step with "Setup could not be saved. Try again." and the
   settings are never written ([`ios/BoltrigTests/OnboardingTests.swift:58`](../../../ios/BoltrigTests/OnboardingTests.swift)
   `"settings are not written when the name was not saved"`).
7. Pressing Start on Ready calls `onFinished`, which re-reads the account and flips the root
   destination ([`ios/Boltrig/App/BoltrigApp.swift:136`](../../../ios/Boltrig/App/BoltrigApp.swift)
   `"store.onFinished = { Task { await session.refreshAccount() } }"`).

### 5.11 The one-press provider rule

`ProviderSetupStore.complete()` is a small state machine
([`ios/Boltrig/Session/ProviderSetupStore.swift:118`](../../../ios/Boltrig/Session/ProviderSetupStore.swift)
`"func complete() async -> Bool {"`):

1. A cached proposal short-circuits to `approveAndConnect`, so the key is never resubmitted.
2. Empty key and empty model with a saved but unready key means `activate`; empty key and
   empty model with nothing to do passes the step.
3. Missing model, missing address where one is required, or a missing key where one is
   required, all refuse locally with a sentence and send nothing
   ([`:130`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"message = Copy.incomplete"`).
4. The submission is built, and **the key field is blanked before the first `await`**
   ([`:152`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"apiKey = \"\""`),
   so nothing on screen holds it once it is sent and a second press cannot resend it.
   `ProviderSetupTests/testProviderClearsTheKeyBeforeAwaitingAndSendsItOnce` reads
   `store.apiKey` from inside the stub handler, while the store is awaiting, and asserts it
   is already empty.
5. A typed address always wins; failing that, a non-native provider silently submits the
   catalogue's published address ([`:147`](../../../ios/Boltrig/Session/ProviderSetupStore.swift)
   `"baseURL: typedAddress.isEmpty ? rules.publishedBaseURL(trimmedProvider) : typedAddress"`).
6. `PUT /v1/ai-keys` resolves to one of four outcomes
   ([`ios/Boltrig/Models/ProviderModels.swift:123`](../../../ios/Boltrig/Models/ProviderModels.swift)
   `"enum AIKeyOutcome: Equatable {"`):
   - `applied` goes to the gateway read-back.
   - `pendingHuman` means the server raised an approval for the person's own submission, and
     the same press answers it via `POST /v1/ai-keys/proposals/{id}/approve`.
   - `pending` means the decision sits with an administrator: the proposal is cached and the
     step holds ([`:186`](../../../ios/Boltrig/Session/ProviderSetupStore.swift)
     `"case let .pending(next), let .pendingHuman(next):"`).
   - `refused` shows the server's sentence, capitalised and full-stopped, unchanged
     otherwise ([`ios/Boltrig/Networking/BoltrigError.swift:82`](../../../ios/Boltrig/Networking/BoltrigError.swift)
     `"let first = reason.prefix(1).uppercased()"`).
7. `confirmGatewayReady` distinguishes "not knowing" from "knowing it is broken": an
   unreachable read-back **passes** the step with "Provider saved. We couldn't confirm it is
   reachable.", and only a positive `gateway_ready == false` holds it
   ([`ios/Boltrig/Session/ProviderSetupStore.swift:233`](../../../ios/Boltrig/Session/ProviderSetupStore.swift)
   `"guard let refreshed = try? await client.aiKeys() else {"`).
8. The three provider routes turn server-explained refusals into outcomes rather than throws,
   on 4xx and on 503 alike; anything without a sentence is still thrown
   ([`ios/Boltrig/Networking/BoltrigClient+Onboarding.swift:45`](../../../ios/Boltrig/Networking/BoltrigClient+Onboarding.swift)
   `"private func aiKeyOutcome(path: String, method: String, body: Data?)"`).
   `OnboardingTests/testClientTurnsServerSentencesIntoOutcomesAndThrowsTheRest` pins both
   directions, including that a 403 and a dead token still throw.
9. A dead proposal (any other approve outcome) is dropped, not held, so the next press starts
   fresh ([`ios/Boltrig/Session/ProviderSetupStore.swift:195`](../../../ios/Boltrig/Session/ProviderSetupStore.swift)
   `"proposal = nil"`).

### 5.12 Debug entry points

Debug builds accept launch arguments handled in `RootView.task`
([`ios/Boltrig/App/BoltrigApp.swift:60`](../../../ios/Boltrig/App/BoltrigApp.swift)
`"if CommandLine.arguments.contains(\"-boltrigOnboarding\")"`):
`-boltrigPreview` with `-boltrigTab today|chat|settings` and `-boltrigEmptyChat` opens a
client-free preview workspace, and `-boltrigOnboarding` with
`-boltrigStep name|provider|vision|ready` opens first-run setup against
`SetupPreviewProtocol`, a `URLProtocol` that answers five routes and 404s everything else
([`ios/Boltrig/Support/SetupPreview.swift:16`](../../../ios/Boltrig/Support/SetupPreview.swift)
`"switch (method, path) {"`). The preview workspace also has a sign-in-screen entrance,
also `#if DEBUG` ([`ios/Boltrig/Views/Auth/AuthFlowView.swift:184`](../../../ios/Boltrig/Views/Auth/AuthFlowView.swift)
`"Button(\"Explore the preview workspace\")"`).

---

## 6. Data

The app has **no database, no migrations, no indexes and no cache of the record**. Everything
it shows is fetched on view and discarded. There are exactly three places where anything
survives a process:

| Store | Key | Contents | Protection | Lifetime |
| --- | --- | --- | --- | --- |
| Keychain, `kSecClassGenericPassword` | service `ai.boltrig.app`, account `session` | `StoredSession` as JSON: instance URL, token id, token secret, creation date | `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` ([`ios/Boltrig/Support/Keychain.swift:27`](../../../ios/Boltrig/Support/Keychain.swift) `"kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly"`) | Until sign-out, instance change, a 401/403 at restore, or the 90-day token expiry |
| `UserDefaults.standard` | `boltrig.instanceURL` | The chosen instance URL, and only when it is not the hosted default ([`ios/Boltrig/Support/BoltrigEnvironment.swift:71`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"if let url, url != BoltrigEnvironment.hostedInstanceURL {"`) | None; it is not a secret | Until changed or reset to the default |
| App bundle (read only) | `ProviderCatalogue.json`, `FamiliarIsland/familiar-island.html` and its manifest, `Assets.xcassets` | The models.dev snapshot (403,955 bytes), the shader page (163,760 bytes), the icon and accent colour | Signed as part of the app | The build |

**The device-only flag is load-bearing.** `ThisDeviceOnly` means an encrypted backup restored
onto a second phone does not carry a signed-in session with it, stated in the file's own
comment ([`ios/Boltrig/Support/Keychain.swift:5`](../../../ios/Boltrig/Support/Keychain.swift)
`"a backup restored onto another phone does"`). `AfterFirstUnlock` (rather than
`WhenUnlocked`) means a background refresh could read it, which today nothing does.

**The URLSession stores are ephemeral.** `SessionStore` defaults to
`URLSessionConfiguration.ephemeral` ([`ios/Boltrig/Session/SessionStore.swift:40`](../../../ios/Boltrig/Session/SessionStore.swift)
`"configuration: URLSessionConfiguration = .ephemeral"`), so no cookie, credential or
response cache is written to disk. The token client additionally refuses cookies outright
([`:330`](../../../ios/Boltrig/Session/SessionStore.swift) `"config.httpShouldSetCookies = false"`).
The island's web view uses a non-persistent data store
([`ios/Boltrig/Familiar/FamiliarIslandController.swift:112`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"configuration.websiteDataStore = .nonPersistent()"`).

**What leaves the phone.** Email and password (sign-in only), the display name, chat message
text, attachment bytes as base64 inside the chat body, settings values, and the TOTP code.
The privacy manifest declares five collected types, all linked, none for tracking, all for
App Functionality ([`ios/Boltrig/PrivacyInfo.xcprivacy:11`](../../../ios/Boltrig/PrivacyInfo.xcprivacy)
`"<key>NSPrivacyCollectedDataTypes</key>"`): Email Address, Name, User ID, Photos or Videos,
Other User Content. One accessed-API reason is declared, `CA92.1` for UserDefaults
([`:84`](../../../ios/Boltrig/PrivacyInfo.xcprivacy) `"<string>CA92.1</string>"`).

**Retention on the phone is zero.** Nothing is logged to disk. The only logging is the
unified log, at INFO, for island reports, and it is marked `privacy: .public` because it
carries no identifiers ([`ios/Boltrig/Familiar/FamiliarIslandController.swift:137`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"Self.log.info(\"island report:"`). The controller keeps at most twenty reports in memory
([`:136`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"if reports.count > 20 { reports.removeFirst() }"`).

---

## 7. Configuration surface

The app has **no runtime configuration file and no environment variables**. Its behaviour is
set by five compile-time constants, one persisted user choice, and the Xcode build settings.

### 7.1 Compile-time constants

| Constant | Value at this commit | What it changes | What breaks if it is wrong |
| --- | --- | --- | --- |
| `BoltrigEnvironment.hostedInstanceURL` | `https://dev.boltrig.ai` ([`ios/Boltrig/Support/BoltrigEnvironment.swift:10`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"URL(string: \"https://dev.boltrig.ai\")!"`) | The default instance, and the value `isHostedInstance` compares against | Every first-run sign-in goes to the wrong host. A stored session for the old default is silently discarded at the next launch (5.1 step 4), signing every existing installation out. The comment says to move this to production once `app.boltrig.ai` serves the product ([`:8`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"dev.boltrig.ai is the live preview host today"`) |
| `BoltrigEnvironment.accessTokenLifetimeDays` | `90` ([`:24`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"static let accessTokenLifetimeDays = 90"`) | The `ttl_days` sent when minting | Above 365 the server silently clamps it ([`boltrig/identity/tokens.py:48`](../../../boltrig/identity/tokens.py) `"return now + timedelta(days=min(days, MAX_TTL_DAYS))"`); at or below zero it silently becomes the server default of 90 ([`:47`](../../../boltrig/identity/tokens.py) `"days = ttl_days if ttl_days and ttl_days > 0 else DEFAULT_TTL_DAYS"`). Neither is reported to the phone |
| `BoltrigEnvironment.accountDeletionAvailable` | `false` ([`:29`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"static let accountDeletionAvailable = false"`) | Whether the Delete account button is enabled and whether `deleteAccount` may reach the network | Flipping it true before `DELETE /v1/me` exists sends a password to a route that does not exist. That route is absent from the pinned tree (bounded: `rg -n 'delete\("/v1/me"' boltrig/` returns nothing, 2026-08-24) |
| `BoltrigEnvironment.privacyPolicyURL` / `termsURL` / `supportURL` | `https://boltrig.ai/privacy`, `/terms`, `https://boltrig.ai` ([`:14`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"static let privacyPolicyURL = URL(string: \"https://boltrig.ai/privacy\")!\""`) | Three links in Settings, About | The code itself records that these pages do not exist yet ([`:12`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"These pages do not exist on boltrig.ai yet"`), and external TestFlight is blocked on the privacy one ([`docs/IOS-TESTFLIGHT-RUNBOOK.md:135`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md) `"the privacy policy at the linked URL"`) |
| `BoltrigEnvironment.desktopDownloadURL` | the GitHub releases page ([`:21`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"https://github.com/wlilley93/boltrig/releases/latest"`) | The "Download Boltrig Desktop" link | Nothing breaks; the comment records that no server route publishes this address |
| `ProviderCatalogue.pinnedRevision` | `318e78edb69805bb278d841495a5e317044d9d9b` ([`ios/Boltrig/Models/ProviderCatalogue.swift:30`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"static let pinnedRevision ="`) | Nothing at runtime; it is what `OnboardingTests` asserts the bundled file's `revision` equals | A bump without re-running the sync script, or the reverse, fails that test and nothing else |
| `SpeechResolution.familiarFallbackVoices` | `pocket-voice: familiar`, `fish: c8f64deb...` ([`ios/Boltrig/Speech/SpeechResolution.swift:12`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"static let familiarFallbackVoices: [String: String] = ["`) | Which voice id is sent for a bound provider | A provider that is bound but absent from this table yields `voiceID == nil`, which means silence, not a default voice |
| `LinkedDevice.liveWindow` | `20` seconds ([`ios/Boltrig/Models/LinkedDevice.swift:14`](../../../ios/Boltrig/Models/LinkedDevice.swift) `"static let liveWindow: TimeInterval = 20"`) | Whether a computer reads "On" | Too small and a live desktop reads offline between its three-second polls; too large and a dead one reads on |
| `FamiliarIslandController.phenotypeInterval` | `3` seconds ([`ios/Boltrig/Familiar/FamiliarIslandController.swift:28`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"static let phenotypeInterval: TimeInterval = 3"`) | Poll rate for `GET /v1/familiar/phenotype` | It is the app's only polling loop; shortening it multiplies requests per looking minute |

### 7.2 The one persisted choice

`boltrig.instanceURL` in `UserDefaults.standard`. Parsed by `InstanceAddress.parse`, which
prepends `https://` when no scheme is given, lowercases the host, and refuses anything whose
scheme is not `https`, stripping path, query, fragment, user and password
([`ios/Boltrig/Support/BoltrigEnvironment.swift:46`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"static func parse(_ text: String) -> URL? {"`). The stated reason is that the session
cookie and the token both travel in the clear otherwise, and App Transport Security would
refuse the connection anyway ([`:40`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"Only https is accepted"`). Proven by
`ClientAndParsingTests/testInstanceAddressParsing`, which pins the rewrite of
` https://My-Box.local:8443/console?x=1 ` to `https://my-box.local:8443` and the refusal of
plain http.

### 7.3 Build settings that change behaviour

| Setting | Value | Effect |
| --- | --- | --- |
| `IPHONEOS_DEPLOYMENT_TARGET` | `17.0` ([`ios/Boltrig.xcodeproj/project.pbxproj:268`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"IPHONEOS_DEPLOYMENT_TARGET = 17.0;"`) | Floor for every API used, including `onChange(of:initial:)`, `ContentUnavailableView` and `callAsyncJavaScript` |
| `TARGETED_DEVICE_FAMILY` | `1` ([`:362`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"TARGETED_DEVICE_FAMILY = 1;"`) | iPhone only. No iPad, no Mac Catalyst |
| `INFOPLIST_KEY_UISupportedInterfaceOrientations_iPhone` | portrait ([`:351`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"UIInterfaceOrientationPortrait;"`) | One orientation; no landscape layout exists |
| `PRODUCT_BUNDLE_IDENTIFIER` | `ai.boltrig.app` ([`:357`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"PRODUCT_BUNDLE_IDENTIFIER = ai.boltrig.app;"`) | Also the Keychain service name and the unified-log subsystem, so all three move together |
| `DEVELOPMENT_TEAM` | `5B68P8YVT8` ([`:342`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"DEVELOPMENT_TEAM = 5B68P8YVT8;"`) | Signing identity; also hard-coded in `ExportOptions.plist` ([`ios/ExportOptions.plist:14`](../../../ios/ExportOptions.plist) `"<string>5B68P8YVT8</string>"`) |
| `CODE_SIGN_STYLE` | `Automatic`, all four configurations | Archive needs `-allowProvisioningUpdates` and a signed-in Xcode |
| `MARKETING_VERSION` / `CURRENT_PROJECT_VERSION` | `1.0` / `1` ([`:356`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"MARKETING_VERSION = 1.0;"`) | Rendered by `BoltrigEnvironment.versionLabel` in Settings, About. The build number must be bumped per upload ([`docs/IOS-TESTFLIGHT-RUNBOOK.md:30`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md) `"Build number must be unique per upload."`) |
| `ENABLE_USER_SCRIPT_SANDBOXING` | `YES`, both project configurations ([`:253`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"ENABLE_USER_SCRIPT_SANDBOXING = YES;"`) | No build phase may write outside its declared outputs. There are no script phases, so nothing is affected today |
| `ITSAppUsesNonExemptEncryption` | `false` ([`ios/Boltrig/Info.plist:7`](../../../ios/Boltrig/Info.plist) `"<key>ITSAppUsesNonExemptEncryption</key>"`) | No export-compliance questionnaire per upload. True only while the app is https-only |

`Info.plist` is deliberately almost empty: everything else is generated
(`GENERATE_INFOPLIST_FILE = YES`), and the file is excluded from the synchronized folder's
resources so it is not also copied into the bundle
([`ios/Boltrig.xcodeproj/project.pbxproj:28`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"Info.plist,"`).

### 7.4 Launch arguments (debug builds only)

`-boltrigPreview`, `-boltrigTab today|chat|settings`, `-boltrigEmptyChat`,
`-boltrigOnboarding`, `-boltrigStep name|provider|vision|ready`
([`ios/Boltrig/App/BoltrigApp.swift:57`](../../../ios/Boltrig/App/BoltrigApp.swift)
`"Launch arguments for simulator captures"`).

### 7.5 Test-only environment

`BOLTRIG_LIVE_EMAIL`, `BOLTRIG_LIVE_PASSWORD`, optional `BOLTRIG_LIVE_INSTANCE`, read by
`LiveContractTests` ([`ios/BoltrigTests/LiveContractTests.swift:21`](../../../ios/BoltrigTests/LiveContractTests.swift)
`"guard let e = env[\"BOLTRIG_LIVE_EMAIL\"], let p = env[\"BOLTRIG_LIVE_PASSWORD\"]"`).
They are passed on the `xcodebuild` command line with a `TEST_RUNNER_` prefix, which
xcodebuild strips before handing them to the runner
([`:8`](../../../ios/BoltrigTests/LiveContractTests.swift) `"TEST_RUNNER_BOLTRIG_LIVE_EMAIL=..."`).
Absent, the whole class skips itself.

---

## 8. PROCESS

### 8.1 Which host can build it, and why only that one

**Only the M4.** The build needs Xcode 26 on macOS
([`ios/README.md:14`](../../../ios/README.md) `"Requires Xcode 26 on a Mac."`), and the
handover states the constraint as an instruction
([`docs/HANDOVER-2026-08-22-ios-app.md:691`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"Build and test only on the M4** (the beelink has no Xcode)"`). Nothing in CI builds it
(bounded: `rg -n -i 'xcodebuild|ios|swift' .github/` returns nothing across
`ci.yml`, `release.yml`, `security.yml`, 2026-08-24, pinned tree), so the phone app has no
automated gate anywhere: its only verification is a person running `xcodebuild test` on a
Mac.

### 8.2 Bring-up on a fresh Mac

1. Sync `ios/` to the Mac.
2. `cd ios && open Boltrig.xcodeproj`, pick an iPhone simulator, Run
   ([`ios/README.md:19`](../../../ios/README.md) `"open Boltrig.xcodeproj"`).
3. Adding a Swift file needs **no project edit**: both targets use file-system synchronized
   root groups ([`ios/Boltrig.xcodeproj/project.pbxproj:36`](../../../ios/Boltrig.xcodeproj/project.pbxproj)
   `"isa = PBXFileSystemSynchronizedRootGroup;"`), and both `Sources` build phases are empty
   ([`:191`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"isa = PBXSourcesBuildPhase;"`).
4. Running on a real iPhone needs a signing team selected
   ([`ios/README.md:34`](../../../ios/README.md) `"needs a signing team selected under Signing and Capabilities"`).

### 8.3 Running the tests

```
xcodebuild -project Boltrig.xcodeproj -scheme Boltrig \
  -destination 'platform=iOS Simulator,name=iPhone 17' test
```

**Leave signing on.** The Keychain round-trip test needs a signed host app and skips itself
under `CODE_SIGNING_ALLOWED=NO` with `errSecMissingEntitlement` (-34018)
([`ios/BoltrigTests/ClientAndParsingTests.swift:190`](../../../ios/BoltrigTests/ClientAndParsingTests.swift)
`"} catch let error as Keychain.KeychainError where error.status == -34018 {"`).
The README's build command uses `CODE_SIGNING_ALLOWED=NO`; the test command deliberately
does not ([`ios/README.md:31`](../../../ios/README.md) `"Keychain round-trip test needs a signed host app and skips itself"`).

### 8.4 The live run against a real instance

`LiveContractTests` is the only suite that touches a network. It signs in, asserts the
Familiar switch, performs the first-screen reads (`chatConfig`, `capabilities`,
`conversations`, `approvals`, `devices`, `tokens`, `readiness`), sends one short turn with a
90-second deadline, and signs out, which revokes the phone's token
([`ios/BoltrigTests/LiveContractTests.swift:29`](../../../ios/BoltrigTests/LiveContractTests.swift)
`"func testSignInAdoptionReadsAndOneChatTurnAgainstTheInstance() async throws {"`).
**Use a throwaway account**: the test switches the account's companion to Familiar by design
([`:11`](../../../ios/BoltrigTests/LiveContractTests.swift) `"Use a throwaway account"`).
The suite records that it accepts a failed turn as a truthful outcome, asserting only that
the copy is non-empty and the session is intact
([`:63`](../../../ios/BoltrigTests/LiveContractTests.swift) `"if chat.turnFailed {"`).
The handover records that this run **had not yet been performed** when it was written
([`docs/HANDOVER-2026-08-22-ios-app.md:705`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"run live; see \"Blocked\" below."`).

### 8.5 Rebuilding Familiar's island after a renderer change

1. `make familiar-island` runs the worker's vite island build and then the sync script
   ([`Makefile:249`](../../../Makefile) `"cd apps/worker && $(PNPM) run build:island"`).
2. The sync writes the page plus a manifest recording `v`, `sourceCommit`, `fragSha256` and
   `htmlBytes` ([`apps/worker/scripts/sync-familiar-island.mjs:66`](../../../apps/worker/scripts/sync-familiar-island.mjs)
   `"const manifest = {"`).
3. `make familiar-island-check` rebuilds into a scratch directory and **byte-compares**
   against the committed page, and separately re-hashes the shader against the manifest
   ([`:94`](../../../apps/worker/scripts/sync-familiar-island.mjs) `"if (!rebuilt.equals(committed)) {"`;
   [`:83`](../../../apps/worker/scripts/sync-familiar-island.mjs) `"if (manifest.fragSha256 !== fragNow) {"`).
   It is wired into `worker-quality` ([`Makefile:246`](../../../Makefile)
   `"$(MAKE) --no-print-directory familiar-island-check"`), so a stale bundled page fails
   the worker gate on any host, not only the Mac.
4. `apps/worker/tests/familiarIsland.test.ts` additionally asserts the page is under 200 KB,
   has no external `<script src=>` or `<link>`, and that its CSP `sha256-` hash really is the
   hash of its own inline script
   ([`apps/worker/tests/familiarIsland.test.ts:402`](../../../apps/worker/tests/familiarIsland.test.ts)
   `"it(\"pins its inline script by the hash its CSP names\""`). The page at this commit is
   163,760 bytes, matching its manifest.

### 8.6 Re-syncing the provider catalogue

`ios/scripts/sync-provider-catalogue.sh` copies
`apps/worker/src/components/onboarding/modelsDevCatalogue.json` over
`ios/Boltrig/Resources/ProviderCatalogue.json`; `--check` exits 1 when they differ
([`ios/scripts/sync-provider-catalogue.sh:21`](../../../ios/scripts/sync-provider-catalogue.sh)
`"if cmp -s \"$source_file\" \"$target_file\"; then"`). At this commit the two files are
byte-identical (verified: `cmp -s` succeeds, both md5
`044b45d31319d6a931b71d8b76e7423b`, 2026-08-24, pinned tree). `pinnedRevision` must be bumped
in the same change, because `OnboardingTests` compares the decoded `revision` to it
([`ios/BoltrigTests/OnboardingTests.swift:194`](../../../ios/BoltrigTests/OnboardingTests.swift)
`"run ios/scripts/sync-provider-catalogue.sh and bump pinnedRevision together"`).
**The script is not wired into any Makefile target or CI job** (bounded: `rg -n
'sync-provider-catalogue' . --glob '!node_modules'`, 2026-08-24, pinned tree, matches only
the script itself and `ios/README.md`), so the only thing that catches drift is the Swift
test, which runs only on a Mac.

### 8.7 Simulator captures

Debug builds take the launch arguments in 7.4; captures live in
`docs/design/evidence/2026-08-ios-familiar/`
([`docs/HANDOVER-2026-08-22-ios-app.md:698`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"Captures live in"`).

### 8.8 Diagnosing the presence

Island reports go to the unified log at INFO under subsystem `ai.boltrig.app`:
`log show --info --predicate 'subsystem == "ai.boltrig.app"'`
([`ios/README.md:69`](../../../ios/README.md) `"log show --info --predicate 'subsystem =="`).
The controller keeps the last twenty reports in `reports` for a debugger.
Budgets measured on the simulator are recorded in the handover: page 163,384 bytes as built
then, `ready` at 1.0 s (the 500 ms target missed on the simulator), hero 59 to 60 fps,
conversation 30 fps, zero frames while another app is in front, 1 fps under Reduce Motion,
WebContent process 20.6 MB, one phenotype request per 3 s
([`docs/HANDOVER-2026-08-22-ios-app.md:608`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"page 163,384 bytes"`).
Those numbers were taken on a simulator and are explicitly a floor, not a device measurement
([`:664`](../../../docs/HANDOVER-2026-08-22-ios-app.md) `"Measure `ready` and memory on a real iPhone"`).

### 8.9 Archive, export and upload

1. Bump the build number: pass `CURRENT_PROJECT_VERSION=<increasing integer>` on the archive
   command ([`docs/IOS-TESTFLIGHT-RUNBOOK.md:47`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md)
   `"CURRENT_PROJECT_VERSION=\"$BUILD\""`).
2. `xcodebuild ... -destination 'generic/platform=iOS' -archivePath build/Boltrig.xcarchive
   -allowProvisioningUpdates archive`.
3. `xcodebuild -exportArchive -exportOptionsPlist ExportOptions.plist -exportPath
   build/export`, which produces `build/export/Boltrig.ipa`. The export options pin method
   `app-store-connect`, automatic signing, symbol upload, and
   `manageAppVersionAndBuildNumber = false`
   ([`ios/ExportOptions.plist:8`](../../../ios/ExportOptions.plist) `"<string>app-store-connect</string>"`).
4. Upload needs Will's Apple login: Transporter, or change `destination` to `upload` and
   supply an App Store Connect API key
   ([`docs/IOS-TESTFLIGHT-RUNBOOK.md:58`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md) `"Upload **[WILL]**"`).
5. The App Privacy answers in App Store Connect must mirror `PrivacyInfo.xcprivacy`
   ([`:70`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md) `"the two must agree"`); the runbook
   carries the table and the draft review notes.

**What blocks each stage** ([`docs/IOS-TESTFLIGHT-RUNBOOK.md:131`](../../../docs/IOS-TESTFLIGHT-RUNBOOK.md)
`"## 6. What blocks each stage, precisely"`): internal TestFlight needs only the App Store
Connect record and the upload; external TestFlight needs a resolving privacy policy URL, a
support URL that answers, and beta review; store submission needs the review account, in-app
account deletion with its server route, terms, and a mailbox.

### 8.10 Recovery paths

| Situation | What the app does | What a person does |
| --- | --- | --- |
| Token revoked elsewhere | Next request 401s; `restore()` clears the vault and shows the sign-in screen | Sign in again |
| Instance unreachable at launch | `.unreachable`, the token is kept | "Try again", or "Sign in again" to clear it ([`ios/Boltrig/App/BoltrigApp.swift:172`](../../../ios/Boltrig/App/BoltrigApp.swift) `"Task { await session.retryRestore() }"`) |
| Phone lost | Nothing automatic | Revoke the key from the web token list, where it appears as "iPhone app, signed in yyyy-MM-dd" ([`ios/README.md:45`](../../../ios/README.md) `"The token shows up in the web app's token list"`) |
| Wrong instance chosen | Sign-out and vault clear on change | "Back to the hosted Boltrig" in the instance sheet ([`ios/Boltrig/Views/Auth/AuthFlowView.swift:412`](../../../ios/Boltrig/Views/Auth/AuthFlowView.swift) `"Button(\"Back to the hosted Boltrig\")"`) |
| Island broken or missing | Badge, permanently for a missing page, until relaunch for a fallback | Nothing; the app is fully usable |
| Account deletion wanted | Screen is read-only and points at support | Ask support ([`ios/Boltrig/Views/Settings/DeleteAccountView.swift:26`](../../../ios/Boltrig/Views/Settings/DeleteAccountView.swift) `"Ask support and it will be done for you."`) |

---

## 9. Failure modes and fail-open / fail-closed posture

Every guard in the app, which way it fails, and the proof.

| Guard | Fails | Proof |
| --- | --- | --- |
| Instance scheme | **Closed.** A non-https address parses to nil and the sheet refuses it | [`ios/Boltrig/Support/BoltrigEnvironment.swift:52`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"components.scheme?.lowercased() == \"https\" else { return nil }"`; `ClientAndParsingTests/testInstanceAddressParsing` |
| Restored token bound to another instance | **Closed.** Cleared without a request | [`ios/Boltrig/Session/SessionStore.swift:75`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard stored.instanceURL == instanceURL else {"`; `SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken` |
| 401 or 403 at restore | **Closed.** Vault cleared, signed out | [`:85`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .unauthenticated, .forbidden:"`; `SessionStoreTests/testRestoreWithARevokedTokenSignsOut` |
| Network failure at restore | **Open, deliberately.** Token kept, unreachable screen shown | [`:88`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .unreachable, .server:"`; `SessionStoreTests/testRestoreWhileOfflineKeepsTheToken`. This is correct: a flaky network must not sign a person out |
| Password length at forced change | **Closed, client-side.** Twelve characters checked before the request | [`:143`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard new.count >= 12 else {"`; `SessionStoreTests` asserts no request is made |
| Display name shape | **Closed, client-side**, and again server-side | [`ios/Boltrig/Session/OnboardingStore.swift:167`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"static func normalizedName(_ raw: String) -> String? {"`; `OnboardingTests/testNameRuleMatchesTheServer` |
| Token revocation on sign-out | **OPEN.** `try?` swallows any failure and the vault is cleared regardless | [`ios/Boltrig/Session/SessionStore.swift:213`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)"`. See RISK-1802 |
| Cookie session close after minting | **OPEN.** `try?` | [`:286`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await sessionClient.logout()"`. See RISK-1803 |
| Familiar adoption | **OPEN by design.** A failed write reports one sentence and sign-in continues | [`:253`](../../../ios/Boltrig/Session/SessionStore.swift) `"} catch {"`; `SessionStoreTests/testFailedAdoptionWriteSaysSoAndStillSignsIn` |
| Adoption announcement | **OPEN by design.** `try?`, described as cosmetic on the server | [`ios/Boltrig/Networking/BoltrigClient.swift:95`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"purely cosmetic on the server"` |
| Linked-device read on Today | **OPEN by design.** `try?`; not knowing is not an error | [`ios/Boltrig/Session/AppStore.swift:101`](../../../ios/Boltrig/Session/AppStore.swift) `"not knowing is not an error here"`; `LinkedDeviceTests/testDevicesFailureLeavesTheRestOfTodayIntact` |
| Approvals or conversations read on Today | **Closed to the person.** `loadError` renders a banner and the lists stay empty | [`:104`](../../../ios/Boltrig/Session/AppStore.swift) `"loadError = (error as? BoltrigError)?.errorDescription"` |
| Unknown chat event | **OPEN by design.** `.other(type:)`, never a failed turn | [`ios/Boltrig/Networking/ChatEvent.swift:89`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"return .other(type: type)"`; `ClientAndParsingTests/testChatEventMapping` |
| Malformed SSE frame | **OPEN by design.** Synthetic `malformed_event` frame | [`:120`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"return [\"type\": \"malformed_event\"]"`; `ClientAndParsingTests/testSSEParserJoinsDataLinesAndIgnoresOtherFields` |
| Follow returning 409 | **OPEN by design.** `.idle`, not an error | [`ios/Boltrig/Networking/BoltrigClient+Chat.swift:41`](../../../ios/Boltrig/Networking/BoltrigClient+Chat.swift) `"if http.statusCode == 409 {"`; `ChatSessionTests/testFollowIdleIsNotAnError` |
| Stale `active_run_id` after a follow | **Closed.** The reload never re-follows | [`ios/Boltrig/Session/ChatSession.swift:222`](../../../ios/Boltrig/Session/ChatSession.swift) `"await loadHistory(followActiveRun: false)"`; `ChatSessionTests/testStaleActiveRunWithAnIdleFollowDoesNotLoop` |
| Run cancel on stop | **OPEN.** `try?`; the UI settles either way | [`:237`](../../../ios/Boltrig/Session/ChatSession.swift) `"Task { try? await client.cancelRun(id: runID) }"` |
| `/readyz` returning 503 | **OPEN by design.** 503 is an answer, and its body is the report | [`ios/Boltrig/Networking/BoltrigClient+Account.swift:61`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift) `"|| http.statusCode == 503 else {"`; `AccountSettingsTests/testReadinessTolerates503AndMapsPlainLabels` |
| Appearance write | **Closed with rollback.** The previous value is restored and a notice shown | [`ios/Boltrig/Session/AccountSettingsStore.swift:50`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"appearance = previous"`; `AccountSettingsTests/testAppearanceRollsBackWhenTheWriteFails` |
| `read_replies` write | **Closed with rollback**, and the speaker is told only on success | [`:64`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"readReplies = previous"`; `AccountSettingsTests/testReadRepliesRollsBackAndTellsNobodyWhenTheWriteFails` |
| Account deletion | **Closed twice.** The store refuses before the client, and the client refuses before the request | [`:162`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"guard BoltrigEnvironment.accountDeletionAvailable, let client else {"`; [`ios/Boltrig/Networking/BoltrigClient+Account.swift:72`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift) `"guard BoltrigEnvironment.accountDeletionAvailable else {"`; `AccountSettingsTests/testDeleteAccountNeverReachesTheNetworkWhileUnavailable` asserts `StubURLProtocol.requests.isEmpty` |
| Speech: no voice bound | **Closed to silence.** Nothing invents a default voice | [`ios/Boltrig/Speech/SpeechResolution.swift:6`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"no voice means silence"`; `ReplySpeakerTests/testResolutionFollowsTheSettingTheProviderAndTheVoiceRules` |
| Speech: any failure | **OPEN by design and silent.** Empty catch with a stated reason | [`ios/Boltrig/Speech/ReplySpeaker.swift:60`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"// Silent by design"`; `ReplySpeakerTests/testFailuresAreSilent` |
| Speech: repeat for a run | **Closed.** One spoken reply per run id | [`:43`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"guard !spokenRuns.contains(runID) else { return }"` |
| Speech: audio payload | **Closed.** Rejected unless `ok`, under 12 MB base64, and `audio/*` | [`:53`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"encoded.count <= Self.maxAudioBase64"` |
| Island navigation | **Closed to file URLs only.** Everything else is cancelled | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:159`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"if navigationAction.request.url?.isFileURL == true {"` |
| Island state values | **Closed by clamping.** `[0,1]`, `[1,2]`, exactly eight bands or none | [`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:32`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"func clamped() -> FamiliarIslandState {"`; `FamiliarBridgeTests/testStateEncodesSortedKeysAndClamps` |
| Island missing or in fallback | **OPEN to the badge.** Never blank | [`ios/Boltrig/Familiar/FamiliarPresenceView.swift:5`](../../../ios/Boltrig/Familiar/FamiliarPresenceView.swift) `"the badge otherwise. Never blank."` |
| Genotype identity binding | **Closed.** Only `agent_capability.name.v1` binds; anything else draws the neutral body | [`ios/Boltrig/Familiar/FamiliarGenotype.swift:56`](../../../ios/Boltrig/Familiar/FamiliarGenotype.swift) `"guard let genotype, genotype.source == Self.boundSource else {"`; `FamiliarBridgeTests/testGenotypeIdentity` |
| Provider gateway read-back | **OPEN when unknown, closed when known bad.** An unreachable re-read passes; `gateway_ready == false` holds | [`ios/Boltrig/Session/ProviderSetupStore.swift:228`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"Not knowing and knowing it is broken are different answers"`; `ProviderSetupTests/testUnreachableReReadPasses` and `testGatewayNotReadyHoldsTheStep` |
| Provider catalogue read | **OPEN.** A failed decode falls back to `ProviderCatalogue.minimal`, two rule-bearing entries | [`:63`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"var rules: ProviderCatalogue { catalogue ?? .minimal }"` |
| Second press on Finish | **Closed.** `finishInFlight` | [`ios/Boltrig/Session/OnboardingStore.swift:129`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"guard !finishInFlight else { return false }"`; `OnboardingTests/testFinishWritesProfileThenSettingsOnceUnderConcurrentPresses` |
| Second press on Continue with a key | **Closed.** The field is empty before the first await, so there is nothing to resend | [`ios/Boltrig/Session/ProviderSetupStore.swift:152`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"apiKey = \"\""`; `ProviderSetupTests/testProviderClearsTheKeyBeforeAwaitingAndSendsItOnce` |
| Attachment size | **Closed before the read.** Size from `resourceValues`, then again after reading | [`ios/Boltrig/Support/AttachmentImporter.swift:18`](../../../ios/Boltrig/Support/AttachmentImporter.swift) `"if size > limits.maxBytes { return .refused(tooBig(limits)) }"`; `AttachmentTests/testAFileOverTheLimitIsRefusedBeforeItIsRead` |
| Attachment count and total | **Closed.** Three limits, three sentences | [`ios/Boltrig/Session/ChatSession.swift:258`](../../../ios/Boltrig/Session/ChatSession.swift) `"if attachments.count >= limits.maxCount {"`; `ChatSessionTests/testAttachmentLimitsAreEnforcedWithPlainCopy` |
| Preview workspace writes | **Closed.** A nil client means nothing reaches the network | [`ios/Boltrig/Session/AccountSettingsStore.swift:189`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"guard let client else {"`; `AccountSettingsTests/testPreviewStoreWritesNothingAndShowsEmptyStates` |

**Two guards that are enforced on the SERVER, not here, and the client is honest about it.**

1. The approval posture is read-only on the phone. `BoltrigClient+Account` states that the
   server refuses `PUT` for the phone's key
   ([`ios/Boltrig/Networking/BoltrigClient+Account.swift:6`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift)
   `"The server refuses `PUT` on this route for the phone's key"`), and the screen says so to
   the person ([`ios/Boltrig/Views/Settings/ApprovalsView.swift:39`](../../../ios/Boltrig/Views/Settings/ApprovalsView.swift)
   `"To change this, sign in on the web."`). **This checks out.** The route requires an
   interactive credential class ([`boltrig/kernel/approval_posture_routes.py:25`](../../../boltrig/kernel/approval_posture_routes.py)
   `"if p.actor_tier != \"human\" or not is_interactive_credential(p.credential_kind):"`),
   the interactive set is `session`, `federated`, `dev-header`
   ([`boltrig/config/dev_posture.py:69`](../../../boltrig/config/dev_posture.py)
   `"INTERACTIVE_CREDENTIAL_KINDS = frozenset({\"session\", \"federated\", \"dev-header\"})"`),
   and a personal access token resolves to kind `pat`
   ([`boltrig/identity/tokens.py:201`](../../../boltrig/identity/tokens.py) `"credential_kind=\"pat\","`).
   The client never calls the `PUT`, and there is no write path in
   `AccountSettingsStore` for the posture (bounded: `rg -n 'approvalPosture' ios/` matches
   only the GET wrapper, `loadPosture`, and the read-only view).
2. Whether the phone's Approve button is allowed to answer a given request is decided
   entirely by `boltrig/kernel/hitl_response_auth.py` (assignment, humanity, live grant and
   independence). The client posts and renders whatever comes back; a refusal becomes a
   `notice` and the row stays. That rule belongs to another area of this corpus.

---

## 10. What is proven

### 10.1 The suite

**95 XCTest methods in 12 test classes**, plus two support files
(`StubURLProtocol.swift`, `OnboardingFixtures.swift`) that declare none. Counted by
`grep -cE '^\s*(func|@MainActor func) test' ios/BoltrigTests/*.swift`, 2026-08-24, pinned tree:

| File | Methods | What it binds |
| --- | --- | --- |
| `AccountSettingsTests.swift` | 14 | Appearance write and rollback, read-replies write and rollback, posture read-only, archived list and restore, sessions and keys, this-phone marking, spending decode, `/readyz` 503, deletion refusal, preview isolation |
| `ProviderSetupTests.swift` | 13 | The whole one-press machine: key blanking, self-approval, cached administrator proposal, dead proposal, gateway read-back both ways, managed organisation, self-hosted, published address, verbatim reasons, incomplete input, activate, vision isolation |
| `ClientAndParsingTests.swift` | 12 | Instance parsing, both error envelopes, sign-in decoding, account decoding, SSE framing, event mapping, streamed and queued chat, HTTP failure before the stream, conversation and approval decoding, Keychain round trip |
| `SessionStoreTests.swift` | 12 | Mint and store, adoption in three shapes, wrong password, two-step, forced password change, revoked token, offline restore, other-instance restore, sign-out revocation, instance change |
| `ChatSessionTests.swift` | 11 | History decode and superseded hiding, history failure, follow from zero then reload, idle follow, cursors and truncation, stop, the no-loop property, questions, attachment limits |
| `OnboardingTests.swift` | 11 | Finish ordering under concurrency, finish failure, refused name, skip vision, name step, name rule, client outcome mapping, profile patch, bundled catalogue, catalogue rules, root gate |
| `ReplySpeakerTests.swift` | 6 | Resolution rules, markdown reduction and cap, one request per run with the exact body, silent failures, stop, the workspace wiring |
| `FamiliarBridgeTests.swift` | 5 | Encoding and clamping, report decoding, mode precedence, genotype identity, badge geometry |
| `AttachmentTests.swift` | 5 | Photo shrink, photo refusal, file refused before read, session notices, 413 copy |
| `LinkedDeviceTests.swift` | 3 | Decode and liveness, refresh and disconnect, device failure isolation |
| `PhenotypeTests.swift` | 2 | Reading decode, poll gating |
| `LiveContractTests.swift` | 1 | The gated end-to-end run |

**Two of the 95 skip themselves.** The Keychain round trip skips under
`CODE_SIGNING_ALLOWED=NO` ([`ios/BoltrigTests/ClientAndParsingTests.swift:193`](../../../ios/BoltrigTests/ClientAndParsingTests.swift)
`"throw XCTSkip(\"Keychain needs a signed host app"`) and the live contract skips without
credentials ([`ios/BoltrigTests/LiveContractTests.swift:22`](../../../ios/BoltrigTests/LiveContractTests.swift)
`"throw XCTSkip(\"no BOLTRIG_LIVE_EMAIL"`). With signing on and no live credentials, 94 run
and 1 skips.

**Everything except `LiveContractTests` runs offline** against `StubURLProtocol`, an
in-memory `URLProtocol` keyed by `"METHOD /path"` that also records every request for
assertion ([`ios/BoltrigTests/StubURLProtocol.swift:5`](../../../ios/BoltrigTests/StubURLProtocol.swift)
`"final class StubURLProtocol: URLProtocol {"`). It can also simulate a dead network with
`Answer(fail: true)` ([`:69`](../../../ios/BoltrigTests/StubURLProtocol.swift)
`"client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet))"`), which is
what the offline-restore and unreachable-read-back tests use. A request with no registered
handler fails with `URLError(.unsupportedURL)`, so an unexpected call is loud, not silent
([`:64`](../../../ios/BoltrigTests/StubURLProtocol.swift) `"URLError(.unsupportedURL)"`).

### 10.2 Gates outside the Swift suite that bind this area

- `make familiar-island-check`, inside `worker-quality`, byte-compares the committed island
  page against a fresh build and re-hashes the shader ([`Makefile:252`](../../../Makefile)
  `"familiar-island-check: ## Refuse a committed Familiar island page"`).
- `apps/worker/tests/familiarIsland.test.ts` asserts four properties of the file that lives
  in `ios/`: the pinned shader hash, the byte size against the manifest, self-containment and
  the CSP hash, and that no other companion is named
  ([`apps/worker/tests/familiarIsland.test.ts:26`](../../../apps/worker/tests/familiarIsland.test.ts)
  `"const ISLAND_DIR = resolve(__dirname, \"../../../ios/Boltrig/Resources/FamiliarIsland\");"`).
  This is the **only** automated gate anywhere that reads a file under `ios/`, and it runs
  under the worker's vitest, not Xcode.
- `ios/scripts/sync-provider-catalogue.sh --check`, which no target invokes (8.6).

### 10.3 What is NOT proven

**No invariant in `tests/invariants.yaml` binds any iOS behaviour, and none can.** That file
binds pytest node ids only, cross-checked against `@pytest.mark.invariant` markers in
`tests/` ([`tests/invariants.yaml:3`](../../../tests/invariants.yaml)
`"a one-line meaning plus the pytest node ids"`); an XCTest method has no representation in
it. Bounded: `rg -n -i 'ios|iphone|swift|familiar.island' tests/invariants.yaml`,
2026-08-24, pinned tree, returns only three lines whose match is the substring "ios" inside
"studios". Every requirement in this spec is therefore unbound, which the authoring contract
says is itself a finding: see RISK-1801.

**There are no UI tests.** No `XCUITest` target exists (bounded: `rg -n 'XCUIApplication|XCTestCase.*UI' ios/`,
2026-08-24, pinned tree, returns nothing; the project has exactly two targets, both listed at
[`ios/Boltrig.xcodeproj/project.pbxproj:166`](../../../ios/Boltrig.xcodeproj/project.pbxproj)
`"targets = ("`). Every SwiftUI view in `ios/Boltrig/Views/` and `ios/Boltrig/Familiar/`
(except `FamiliarBadgeView.radialPolygon`, which one test calls) is IMPLEMENTED-UNTESTED.

**Nothing has been run against a live instance.** The handover records the live run as
outstanding and blocked on a throwaway dev account
([`docs/HANDOVER-2026-08-22-ios-app.md:741`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"**The live run** waits on a throwaway dev account."`).

---

## 11. RISKS

RISK-1801: **Nothing automated verifies this area.** No CI job, no Makefile target and no
invariant reaches the Swift tree; the only gate is a person running `xcodebuild test` on the
one Mac. Bounded: `rg -n -i 'xcodebuild|ios|swift' .github/` returns nothing;
`rg -n -i 'ios|iphone|swift' Makefile` matches only the two `familiar-island` targets, whose
work is in `apps/worker`; `tests/invariants.yaml` binds pytest node ids only
([`tests/invariants.yaml:3`](../../../tests/invariants.yaml) `"a one-line meaning plus the pytest node ids"`).

RISK-1802: **Sign-out revokes the token best-effort and clears the vault regardless.** If the
revoke call fails for any reason, including no network, the phone forgets a credential that
is still live on the server for up to 90 days, and the person has no signal that it was not
revoked ([`ios/Boltrig/Session/SessionStore.swift:213`](../../../ios/Boltrig/Session/SessionStore.swift)
`"try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)"`).
`SessionStoreTests/testSignOutRevokesThePhoneToken` covers only the success path.

RISK-1803: **The cookie session is closed best-effort too.** A failed logout leaves a live
web session on the server after the phone has already banked its token
([`:286`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await sessionClient.logout()"`).

RISK-1804: **The phone's key carries the owner's entire grant set.** The client sends only
`{name, ttl_days}` ([`ios/Boltrig/Networking/BoltrigClient.swift:70`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
`"[\"name\": name, \"ttl_days\": ttlDays]"`), and with no `scope` the server stores the
caller's own allow set ([`boltrig/identity/tokens.py:69`](../../../boltrig/identity/tokens.py)
`"requested = requested_scope if requested_scope else list(user_grants.allow)"`). A phone in
a pocket therefore holds an unscoped credential for a superadmin, for 90 days, where the app
itself calls at most about thirty routes.

RISK-1805: **The native-provider set and alias table are a third, ungated copy of a kernel
rule.** `boltrig/identity/bifrost_user_admin.py` is the authority, the web copy is pinned to
it by a test that parses the Python
([`apps/worker/tests/providerCatalogue.test.ts:35`](../../../apps/worker/tests/providerCatalogue.test.ts)
`"const block = /BIFROST_PROVIDERS = frozenset"`), and the Swift copy is pinned to nothing
([`ios/Boltrig/Models/ProviderCatalogue.swift:49`](../../../ios/Boltrig/Models/ProviderCatalogue.swift)
`"static let bifrostSupported: Set<String> = ["`). The Swift comment says the web's test keeps
them equal, which is true of the web copy and not of this one
([`:47`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"A second copy of"`). Both sets
agree today (23 ids and 6 aliases, compared by hand 2026-08-24 against
[`boltrig/identity/bifrost_user_admin.py:21`](../../../boltrig/identity/bifrost_user_admin.py)
`"BIFROST_PROVIDERS = frozenset("` and
[`boltrig/identity/bifrost_user_binding.py:34`](../../../boltrig/identity/bifrost_user_binding.py)
`"_PROVIDER_ALIASES = {"`). A drift would silently send a native provider down the custom
address path, or the reverse.

RISK-1806: **Familiar's voice ids are a second, ungated copy of the character bundle.**
`SpeechResolution.familiarFallbackVoices` hard-codes `fish: c8f64deb39914cfca7f47ccfc3bca82f`
([`ios/Boltrig/Speech/SpeechResolution.swift:14`](../../../ios/Boltrig/Speech/SpeechResolution.swift)
`"\"fish\": \"c8f64deb39914cfca7f47ccfc3bca82f\","`), which is a copy of
[`apps/worker/src/bundles/familiar/character.json:63`](../../../apps/worker/src/bundles/familiar/character.json)
`"\"fish\": \"c8f64deb39914cfca7f47ccfc3bca82f\","`. Nothing keeps them equal; a bundle change
makes the phone request a voice that no longer exists, and the failure is silent by design
(9, speech row).

RISK-1807: **`"not authenticated"` in `sessionReasons` matches nothing the server sends.**
Bounded: `rg -ni 'not authenticated' boltrig/`, 2026-08-24, pinned tree, returns nothing, and
no `HTTPBearer` is used anywhere in `boltrig/`. A 401 carrying that reason would be
classified `.rejected` rather than `.unauthenticated`
([`ios/Boltrig/Networking/BoltrigClient.swift:291`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
`"static let sessionReasons: Set<String> = ["`). The comparison is also exact and
case-sensitive, so a reason that differs only in case would be misclassified.

RISK-1808: **The default instance is a preview host, and changing it signs everyone out.**
`hostedInstanceURL` is `https://dev.boltrig.ai`
([`ios/Boltrig/Support/BoltrigEnvironment.swift:10`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"URL(string: \"https://dev.boltrig.ai\")!"`). Because `restore()` discards a stored session
whose instance does not match ([`ios/Boltrig/Session/SessionStore.swift:75`](../../../ios/Boltrig/Session/SessionStore.swift)
`"guard stored.instanceURL == instanceURL else {"`), the eventual move to a production host is
a silent forced sign-out of every installed copy, with no migration path in the code.

RISK-1809: **Three public links in Settings point at pages that do not exist**, by the code's
own admission ([`ios/Boltrig/Support/BoltrigEnvironment.swift:12`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"These pages do not exist on boltrig.ai yet"`). They ship in the release build and are
reachable from the About section today
([`ios/Boltrig/Views/SettingsView.swift:86`](../../../ios/Boltrig/Views/SettingsView.swift)
`"Link(\"Privacy policy\", destination: BoltrigEnvironment.privacyPolicyURL)"`).

RISK-1810: **The island's navigation policy allows every `file:` URL, not only the bundled
page.** ([`ios/Boltrig/Familiar/FamiliarIslandController.swift:159`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"if navigationAction.request.url?.isFileURL == true {"`). The comment above it claims a
narrower rule ([`:158`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"Only the bundled page may load"`). The page's own CSP is `default-src 'none'` with no
`connect-src`, so nothing in it can currently attempt a navigation, but the guard does not
say what its comment says.

RISK-1811: **The recorded test count is stale by one.** `ios/README.md` says 94 tests
([`ios/README.md:32`](../../../ios/README.md) `"Last measured: 94 tests, 94 passed (2026-08-22)"`),
the tree contains 95 test methods, and the handover already says 95
([`docs/HANDOVER-2026-08-22-ios-app.md:694`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"95 tests, of which one skips itself without a live credential"`). The 95th,
`LiveContractTests`, landed in `16356a79` after the README was measured. A count that is one
low is exactly the kind of number a later reader trusts.

RISK-1812: **`ios/` is not in `.dockerignore`.** No image copies it (3), but every kernel,
fleet and worker build sends 1.3 MB of Swift, a 404 KB JSON snapshot, a 164 KB HTML page and
a 50 KB PNG into the daemon's build context on a box where build memory has been a problem.
Bounded: `grep -n 'ios' .dockerignore` returns nothing, 2026-08-24, pinned tree.

RISK-1813: **`FamiliarVisualIdentity.validPalette` uses `try!` on a regular expression.**
([`ios/Boltrig/Familiar/FamiliarGenotype.swift:79`](../../../ios/Boltrig/Familiar/FamiliarGenotype.swift)
`"let hex = try! NSRegularExpression(pattern:"`). The pattern is a constant so it cannot
throw today, but it is also recompiled on every call, inside a badge that draws per frame.

RISK-1814: **Four decoded fields and one whole rendering path are unreachable from any app
call site**, so a reader can believe the app does more than it does. See BT-REQ-1890 to
BT-REQ-1894 in the requirements table. None is a defect on its own; together they are a map
that does not match the territory.

RISK-1815: **`AttachmentLimits.readableTypes` is read from the server and never used.** The
composer's footnote is a hard-coded sentence
([`ios/Boltrig/Session/ChatSession.swift:34`](../../../ios/Boltrig/Session/ChatSession.swift)
`"Only text files are read. Photos and other files are kept with the message."`), so a
deployment that widens `model_readable_media_types` will have the phone tell people something
untrue. Bounded: `rg -n 'readableTypes' ios/`, 2026-08-24, pinned tree, matches only the
declaration and the decode.

RISK-1816: **`ReplySpeaker` accepts up to 12,000,000 base64 characters, about 9 MB of audio,
decoded whole into memory** on a phone ([`ios/Boltrig/Speech/ReplySpeaker.swift:24`](../../../ios/Boltrig/Speech/ReplySpeaker.swift)
`"static let maxAudioBase64 = 12_000_000"`). The check is after the whole body has already
been read by `session.data(for:)`, so the bound limits what is decoded, not what is received.

RISK-1817: **Attachment bytes travel base64 inside the chat JSON body**, so a 1 MiB total
becomes roughly 1.4 MB of JSON built entirely in memory
([`ios/Boltrig/Models/ChatHistoryModels.swift:79`](../../../ios/Boltrig/Models/ChatHistoryModels.swift)
`"[\"name\": name, \"media_type\": mediaType, \"data\": data.base64EncodedString()]"`).

RISK-1818: **The unreachable screen offers "Sign in again", which calls `signOut()`**, so a
person who taps it while genuinely offline destroys their stored credential and must type a
password ([`ios/Boltrig/App/BoltrigApp.swift:177`](../../../ios/Boltrig/App/BoltrigApp.swift)
`"Button(\"Sign in again\") {"`). The label does not say that.

---

## 12. OPEN QUESTIONS

OQ-1801: **Does the whole app actually compile and pass at this commit?** The last recorded
run is from `feat/ios-app` before `16356a79` and `313ac58a` merged, and it recorded 94 tests.
Nothing in the pinned tree records a run at 19bcae7f. **What would settle it**: one
`xcodebuild -project ios/Boltrig.xcodeproj -scheme Boltrig -destination 'platform=iOS
Simulator,name=iPhone 17' test` on the M4, with signing on, and the numbers written into
`ios/README.md`.

OQ-1802: **Can the phone's Approve button actually approve anything on a single-human
tenant?** The client posts and the server decides
([`boltrig/kernel/hitl_response_auth.py:321`](../../../boltrig/kernel/hitl_response_auth.py)
`"async def authorize_approval_response("`). The sole-author relief is gated on an
interactive credential kind, and a PAT is not interactive
([`boltrig/config/dev_posture.py:69`](../../../boltrig/config/dev_posture.py)
`"INTERACTIVE_CREDENTIAL_KINDS = frozenset({\"session\", \"federated\", \"dev-header\"})"`),
so the phone may be refused exactly where the web would be allowed. I did not read
`approval_response_block` in full and this belongs to the HITL area of this corpus.
**What would settle it**: read `approval_response_block` and `_development_posture_block`
end to end, lines 162 to 269 of `boltrig/kernel/hitl_response_auth.py`, or run the live
contract test with a pending approval on the account.

OQ-1803: **Is the 20-second liveness window right?** `LinkedDevice.liveWindow` is 20 s
against a desktop poll the comment says is 3 s
([`ios/Boltrig/Models/LinkedDevice.swift:5`](../../../ios/Boltrig/Models/LinkedDevice.swift)
`"the desktop's three-second poll"`). I did not verify the desktop's actual interval in
`apps/worker/src-tauri`. **What would settle it**: grep the Tauri source for the presence
heartbeat interval.

OQ-1804: **Why does `SessionStore` hold one `URLSessionConfiguration` and build several
`URLSession`s from it?** `signInSession` and the password-reset session share the
configuration object and therefore its cookie storage
([`ios/Boltrig/Session/SessionStore.swift:196`](../../../ios/Boltrig/Session/SessionStore.swift)
`"session: URLSession(configuration: self.configuration)"`), and neither is ever
`invalidateAndCancel`ed. In an ephemeral configuration this is contained to the process, so I
could not show a leak, only that nothing forces the cookie out. **What would settle it**: a
test that signs in, cancels, and asserts the second session sends no cookie.

OQ-1805: **Is `presentation: .minimised` on release the right shape?** `release(_:)` applies
a minimised state after clearing the owner, but `apply` is a no-op unless `isReady`
([`ios/Boltrig/Familiar/FamiliarIslandController.swift:53`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"apply(FamiliarIslandState(presentation: .minimised))"`), and the queued state is then
flushed on the NEXT claim by another surface, which immediately pushes its own state. I could
not determine whether a frame of the wrong presentation is ever drawn. **What would settle
it**: capture the island's own log while switching tabs on a device.

OQ-1806: **Which iPhone was the 20.6 MB WebContent figure measured on?** The handover says
simulator and calls the numbers a floor
([`docs/HANDOVER-2026-08-22-ios-app.md:664`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"the simulator numbers above are the floor"`). No device measurement exists in the tree.
**What would settle it**: run on a real iPhone with Instruments and record it beside the
simulator numbers.

OQ-1807: **Does `GET /v1/me/settings` really return `active_workspace_id` at the root?**
`Account.decode` reads it from the root object
([`ios/Boltrig/Models/AuthModels.swift:121`](../../../ios/Boltrig/Models/AuthModels.swift)
`"activeWorkspaceID: root[\"active_workspace_id\"] as? String"`), the test fixture supplies
it there, and the field is never used by any view (bounded: `rg -n 'activeWorkspaceID' ios/`,
2026-08-24, pinned tree, matches only `Models/AuthModels.swift` five times, two preview
constructors, and three test files; no file under `ios/Boltrig/Views/` matches). I did
not read `boltrig/kernel/account_profile_routes.py` to confirm the server emits it.
**What would settle it**: read that route's response builder.

---

## 13. Requirements

Ninety-nine rows, `BT-REQ-1800` to `BT-REQ-1898`, all inside this area's allocated block.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1800 | Boltrig for iPhone is a native SwiftUI application whose whole source is the Xcode project under ios/, with one app target and one unit-test target and no third-party package dependency. | IMPLEMENTED-UNTESTED | `ios/Boltrig.xcodeproj/project.pbxproj:166 'targets = (' and :105 'packageProductDependencies = ('` | - |
| BT-REQ-1801 | No container image copies ios/, so a kernel, fleet or worker roll never ships the phone app. | IMPLEMENTED-UNTESTED | `deploy/kernel.Dockerfile:158 'COPY boltrig/ /app/boltrig/' (bounded: no COPY in any of the five Dockerfiles names ios/)` | - |
| BT-REQ-1802 | The app targets iOS 17.0, iPhone only, portrait only. | IMPLEMENTED-UNTESTED | `ios/Boltrig.xcodeproj/project.pbxproj:268 'IPHONEOS_DEPLOYMENT_TARGET = 17.0;', :362 'TARGETED_DEVICE_FAMILY = 1;', :351 'UIInterfaceOrientationPortrait;'` | - |
| BT-REQ-1803 | Only a Mac running Xcode 26 can build or test the app; no CI workflow and no Makefile target does. | IMPLEMENTED-UNTESTED | `ios/README.md:14 'Requires Xcode 26 on a Mac.' (bounded: rg -n -i 'xcodebuild\|ios\|swift' .github/ returns nothing, 2026-08-24)` | - |
| BT-REQ-1804 | The privacy manifest declares five collected data types, all linked to the user, none used for tracking, all for App Functionality, and one accessed-API reason CA92.1 for UserDefaults. | IMPLEMENTED-UNTESTED | `ios/Boltrig/PrivacyInfo.xcprivacy:11 '<key>NSPrivacyCollectedDataTypes</key>' and :84 '<string>CA92.1</string>'` | - |
| BT-REQ-1805 | Sign-in posts email and password to POST /v1/auth/login on a cookie-bearing URLSession and resolves to exactly one of four outcomes: signed in, password change required, two-step enrolment required, or two-step challenge required. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:230 'static func decodeSignIn(_ data: Data) throws -> SignInOutcome {'; BoltrigTests/ClientAndParsingTests/testSignInOutcomeDecoding` | - |
| BT-REQ-1806 | A two-step challenge yields no session and no stored credential until the code is accepted. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:263 'case let .twoFactorRequired(challengeToken):'; BoltrigTests/SessionStoreTests/testTwoFactorRequiredAsksForTheCodeThenSignsIn` | - |
| BT-REQ-1807 | A forced password change is refused on the phone before any request when the new password is shorter than twelve characters or does not match its confirmation. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:143 'guard new.count >= 12 else {'; BoltrigTests/SessionStoreTests/testForcedPasswordChangeIsCompletedBeforeTheTokenIsMinted` | - |
| BT-REQ-1808 | Two-step enrolment shows the otpauth URI, the secret and the recovery codes exactly once and stores none of them. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Models/AuthModels.swift:21 'shown to the person exactly once and never stored by the app' (no test names TwoFactorEnrolment; bounded: rg -n 'TwoFactorEnrolment' ios/BoltrigTests/ returns nothing)` | - |
| BT-REQ-1809 | The ceremony ends by minting a personal access token named '<device model> app, signed in yyyy-MM-dd' with ttl_days 90 on POST /v1/me/tokens. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:283 'mintAccessToken(name: Self.tokenName(), ttlDays:'; BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount` | - |
| BT-REQ-1810 | The only state that survives a launch is one Keychain item holding the instance URL, the token id, the token secret and a creation date, plus the chosen instance address in UserDefaults. | IMPLEMENTED | `ios/Boltrig/Models/AuthModels.swift:145 'struct StoredSession: Codable, Equatable {'; BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount asserts vault.stored` | - |
| BT-REQ-1811 | Keychain items live under the service ai.boltrig.app with kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly, so a backup restored onto another phone carries no session. | IMPLEMENTED | `ios/Boltrig/Support/Keychain.swift:27 'kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly'; BoltrigTests/ClientAndParsingTests/testKeychainRoundTrip` | - |
| BT-REQ-1812 | Every request made after sign-in carries Authorization: Bearer <token> and no CSRF header, on a URLSession that neither sends nor accepts cookies. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:192 'request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")'; ios/Boltrig/Session/SessionStore.swift:330 'config.httpShouldSetCookies = false'; BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount` | - |
| BT-REQ-1813 | A cookie-session request carries the x-boltrig-csrf header on POST, PUT, PATCH and DELETE only. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:188 'if Self.mutatingMethods.contains(method) {'; BoltrigTests/SessionStoreTests/testForcedPasswordChangeIsCompletedBeforeTheTokenIsMinted` | - |
| BT-REQ-1814 | A stored session whose instance URL differs from the current instance is discarded at launch without any network request. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:75 'guard stored.instanceURL == instanceURL else {'; BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken` | - |
| BT-REQ-1815 | A 401 or 403 at restore clears the Keychain and signs out; an unreachable or 5xx keeps the credential and shows the unreachable screen. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:85 'case .unauthenticated, .forbidden:'; BoltrigTests/SessionStoreTests/testRestoreWithARevokedTokenSignsOut and testRestoreWhileOfflineKeepsTheToken` | - |
| BT-REQ-1816 | A non-2xx answer is reduced by reading both server envelopes, {status,reason} and {detail}, and a 401 whose reason is not one of five session reasons is surfaced as the server's own sentence rather than as a demand to sign in. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:269 'if let reason, !sessionReasons.contains(reason) {' and :295 'static func reason(in data: Data) -> String? {'; BoltrigTests/ClientAndParsingTests/testErrorMappingReadsBothEnvelopes` | - |
| BT-REQ-1817 | Sign-out asks the server to revoke this phone's token, then clears the Keychain and returns to the sign-in screen. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:213 'try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)'; BoltrigTests/SessionStoreTests/testSignOutRevokesThePhoneToken` | - |
| BT-REQ-1818 | Sign-out clears the stored credential even when the revoke request fails, so a failed revocation leaves a live token the phone has forgotten. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Session/SessionStore.swift:213 'try? await tokenClient(stored.secret).revokeAccessToken' followed by :214 'try? vault.clear()' (no test covers the failure path; bounded: SessionStoreTests has one sign-out test and it stubs a 200)` | - |
| BT-REQ-1819 | The minted phone token carries the whole grant allow set of its owner, because the client requests no scope. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Networking/BoltrigClient.swift:70 '["name": name, "ttl_days": ttlDays]'; boltrig/identity/tokens.py:69 'requested = requested_scope if requested_scope else list(user_grants.allow)'` | - |
| BT-REQ-1820 | Closing the cookie session after minting is best effort and its failure is not reported. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Session/SessionStore.swift:286 'try? await sessionClient.logout()'` | - |
| BT-REQ-1821 | Pointing the app at another instance signs the current one out, clears the Keychain and persists the new address. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:222 'func useInstance(_ url: URL) async {'; BoltrigTests/SessionStoreTests/testChangingInstancePersistsAndSignsOut` | - |
| BT-REQ-1822 | Only an https address is accepted as an instance, and the parser strips path, query, fragment, user and password and lowercases the host. | IMPLEMENTED | `ios/Boltrig/Support/BoltrigEnvironment.swift:52 'components.scheme?.lowercased() == "https" else { return nil }'; BoltrigTests/ClientAndParsingTests/testInstanceAddressParsing` | - |
| BT-REQ-1823 | An account whose companion is unset or is any id other than familiar is switched to Familiar once, by writing agent.character, then announcing adoption, then re-reading the account. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:246 'try await client.putSettings(["agent.character": CompanionPresence.familiarID])'; BoltrigTests/SessionStoreTests/testAnotherCompanionIsSwitchedToFamiliarOnFirstLoad` | - |
| BT-REQ-1824 | A failed adoption write never blocks sign-in, reports one plain sentence, and skips the announcement. | IMPLEMENTED | `ios/Boltrig/Session/SessionStore.swift:254 'familiarAdoptedNotice = "Boltrig could not set Familiar'; BoltrigTests/SessionStoreTests/testFailedAdoptionWriteSaysSoAndStillSignsIn` | - |
| BT-REQ-1825 | The stored companion identifier is never rendered anywhere in the app. | IMPLEMENTED | `ios/Boltrig/Models/CompanionPresence.swift:5 'The stored id itself is never displayed.'; BoltrigTests/ClientAndParsingTests/testAccountDecodingReadsTheSettingsBag` | - |
| BT-REQ-1826 | The root view renders restoring, unreachable, the sign-in ceremony, first-run setup or the three-tab workspace of Today, Chat and Settings from the session state alone, and shows nothing private before the server has confirmed the account. | IMPLEMENTED-UNTESTED | `ios/Boltrig/App/BoltrigApp.swift:88 'switch session.state {' and :29 'Nothing private renders'; ios/Boltrig/App/ContentView.swift:31 'TabView(selection: $store.selectedTab) {'` | - |
| BT-REQ-1827 | An account without setup.onboarding_version at 1 or above is sent to first-run setup rather than the workspace. | IMPLEMENTED | `ios/Boltrig/App/BoltrigApp.swift:24 'account.onboardingComplete ? .workspace : .onboarding'; BoltrigTests/OnboardingTests/testRootDestinationResolve` | - |
| BT-REQ-1828 | The account's stored theme sets the phone's colour scheme, and system leaves the choice to iOS. | IMPLEMENTED-UNTESTED | `ios/Boltrig/App/ContentView.swift:46 '.preferredColorScheme(accountSettings.appearance.theme.colorScheme)'` | - |
| BT-REQ-1829 | Today reads whether a conversation is working from the server's own flag and never infers it. | IMPLEMENTED | `ios/Boltrig/Models/AppModels.swift:28 'var isWorking: Bool { working ?? false }'; BoltrigTests/ClientAndParsingTests/testConversationsDecodeTheServerShape` | - |
| BT-REQ-1830 | A failed read of the linked computers is not an error and leaves the rest of Today intact. | IMPLEMENTED | `ios/Boltrig/Session/AppStore.swift:102 'if let linked = try? await client.devices() { devices ='; BoltrigTests/LinkedDeviceTests/testDevicesFailureLeavesTheRestOfTodayIntact` | - |
| BT-REQ-1831 | Approve and Not now post a decision to POST /v1/hitl/{id}/respond and remove the card only when the server accepts. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Session/AppStore.swift:147 'try await client.respond(to: approval.id, decision: decision)' (bounded: no test names AppStore.respond; rg -n 'respond' ios/BoltrigTests/ returns nothing)` | - |
| BT-REQ-1832 | A linked computer reads as on only when the server says online and its last-seen time is within twenty seconds. | IMPLEMENTED | `ios/Boltrig/Models/LinkedDevice.swift:24 'guard revokedAt == nil, presence == "online", let lastSeenAt else { return false }'; BoltrigTests/LinkedDeviceTests/testDevicesDecodeAndLivenessIsReadFromLastSeen` | - |
| BT-REQ-1833 | Disconnecting a computer calls DELETE /v1/devices/{id} and drops it from the list. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Devices.swift:11 'func revokeDevice(id: String) async throws {'; BoltrigTests/LinkedDeviceTests/testRefreshLoadsTheLinkedComputersAndDisconnectRevokes` | - |
| BT-REQ-1834 | Archiving a conversation from Today soft-closes it through DELETE /v1/me/conversations/{id} and then refreshes Today. | IMPLEMENTED | `ios/Boltrig/Views/TodayView.swift:222 'if await accountSettings.archive(id: conversation.id) {'; BoltrigTests/AccountSettingsTests/testArchiveSoftClosesAChat` | - |
| BT-REQ-1835 | A chat turn posts message, origin ios, an idempotency key and base64 attachments to POST /v1/chat and reads the reply as a server-sent event stream with a 600 second timeout. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:131 '"origin": "ios",'; BoltrigTests/ClientAndParsingTests/testStreamChatYieldsEventsInOrder` | - |
| BT-REQ-1836 | A 202 answer to a chat post yields exactly one queued event carrying the conversation id, and a non-2xx answer before the stream begins is mapped to a BoltrigError and thrown into the stream. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient.swift:144 'if http.statusCode == 202 {' and :151 'guard (200..<300).contains(http.statusCode) else {'; BoltrigTests/ClientAndParsingTests/testStreamChatReportsAQueuedTurn and testStreamChatSurfacesAnHTTPFailureBeforeTheStream` | - |
| BT-REQ-1837 | Server-sent event frames are split by hand on newline, several data lines in one frame are joined with a newline, and a frame that is not JSON becomes a synthetic malformed_event rather than an error. | IMPLEMENTED | `ios/Boltrig/Networking/SSEByteReader.swift:3 'Lines are split by hand because'; ios/Boltrig/Networking/ChatEvent.swift:120 'return ["type": "malformed_event"]'; BoltrigTests/ClientAndParsingTests/testSSEParserJoinsDataLinesAndIgnoresOtherFields` | - |
| BT-REQ-1838 | Twenty-one wire event types are mapped by name and every other type becomes .other, so an unknown event never fails a turn. | IMPLEMENTED | `ios/Boltrig/Networking/ChatEvent.swift:88 'return .other(type: type)'; BoltrigTests/ClientAndParsingTests/testChatEventMapping` | - |
| BT-REQ-1839 | Conversation history hides superseded messages and messages of any role other than user or assistant. | IMPLEMENTED | `ios/Boltrig/Session/ChatSession.swift:125 '.filter { $0.supersededBy == nil && $0.role != .other }'; BoltrigTests/ChatSessionTests/testHistoryDecodesTheServerShapeAndHidesSupersededMessages` | - |
| BT-REQ-1840 | A run the server reports active is followed once from cursor zero, and the history reload that follows never triggers another follow. | IMPLEMENTED | `ios/Boltrig/Session/ChatSession.swift:222 'await loadHistory(followActiveRun: false)'; BoltrigTests/ChatSessionTests/testStaleActiveRunWithAnIdleFollowDoesNotLoop` | - |
| BT-REQ-1841 | A 409 from the follow route means nothing is running and is reported as idle, and each follow frame carries a cursor and a truncation flag whose true value raises one notice saying earlier activity is not shown. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Chat.swift:41 'if http.statusCode == 409 {'; ios/Boltrig/Session/ChatSession.swift:208 'Earlier live activity is not shown.'; BoltrigTests/ChatSessionTests/testFollowIdleIsNotAnError and testFollowFramesCarryCursorsAndTruncation` | - |
| BT-REQ-1842 | Stop cancels the local stream task and posts POST /v1/runs/{id}/cancel for the live run. | IMPLEMENTED | `ios/Boltrig/Session/ChatSession.swift:237 'Task { try? await client.cancelRun(id: runID) }'; BoltrigTests/ChatSessionTests/testStopPostsTheCancelForTheLiveRun` | - |
| BT-REQ-1843 | A question raised mid-turn is answered on POST /v1/hitl/{id}/answer and the answer is appended to the thread as the person's own message. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Chat.swift:17 'perform(path: "/v1/hitl/\(id)/answer"'; BoltrigTests/ChatSessionTests/testQuestionIsAnsweredOnTheHitlRoute` | - |
| BT-REQ-1844 | Attachment limits come from GET /v1/chat/config, falling back to eight files, 256 KiB each and 1 MiB total when the route cannot be read. | IMPLEMENTED | `ios/Boltrig/Models/ChatHistoryModels.swift:86 'var maxCount: Int = 8'; BoltrigTests/ChatSessionTests/testAttachmentLimitsDefaultWhenConfigIsUnreadable` | - |
| BT-REQ-1845 | A chosen file is refused on size before any of its bytes are read, and a chosen photo is re-encoded as JPEG and shrunk until it fits the per-file limit or refused with the size sentence. | IMPLEMENTED | `ios/Boltrig/Support/AttachmentImporter.swift:17 'let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max' and :33 'static func jpeg(_ image: UIImage, under limit: Int) -> Data? {'; BoltrigTests/AttachmentTests/testAFileOverTheLimitIsRefusedBeforeItIsRead and testAPhotoOverTheLimitIsShrunkToFit` | - |
| BT-REQ-1846 | A 413 answer to a chat post renders one fixed sentence about attachments instead of the raw error. | IMPLEMENTED | `ios/Boltrig/Session/ChatSession.swift:181 'if (error as? BoltrigError)?.status == 413 { copy = Self.attachmentsRejectedCopy }'; BoltrigTests/AttachmentTests/testARejectedUploadShowsPlainCopy` | - |
| BT-REQ-1847 | Reading a reply aloud requires the account setting, an adapter bound to voice.speak and a resolved voice, where a per-character override applies only to the local voice provider and only when it matches the voice-id pattern; any of the three missing means silence and no request. | IMPLEMENTED | `ios/Boltrig/Speech/SpeechResolution.swift:24 'var canSpeak: Bool { enabled && provider != nil && voiceID != nil }' and :30 'if provider == overrideProvider, let override = account.voiceOverrides[familiarID], isValidVoiceID(override)'; BoltrigTests/ReplySpeakerTests/testResolutionFollowsTheSettingTheProviderAndTheVoiceRules` | - |
| BT-REQ-1848 | A finished reply is spoken at most once per run id, through POST /v1/invoke with noun voice and verb voice.speak. | IMPLEMENTED | `ios/Boltrig/Speech/ReplySpeaker.swift:43 'guard !spokenRuns.contains(runID) else { return }'; BoltrigTests/ReplySpeakerTests/testSpeaksOncePerRunWithTheExactRequest` | - |
| BT-REQ-1849 | Spoken text is markdown reduced by ten rewrite rules and capped at fifteen thousand characters. | IMPLEMENTED | `ios/Boltrig/Speech/SpeechResolution.swift:63 'return String(text.prefix(maxSpokenCharacters))'; BoltrigTests/ReplySpeakerTests/testSpeechTextReducesMarkdownLikeTheWeb` | - |
| BT-REQ-1850 | Every speech failure is silent: no error is shown and the reply stays on screen. | IMPLEMENTED | `ios/Boltrig/Speech/ReplySpeaker.swift:60 '// Silent by design'; BoltrigTests/ReplySpeakerTests/testFailuresAreSilent` | - |
| BT-REQ-1851 | Audio is accepted only when the invoke returns ok, the base64 payload is at most twelve million characters, and the content type begins audio/. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Speech/ReplySpeaker.swift:53 'encoded.count <= Self.maxAudioBase64' (testFailuresAreSilent covers a bad base64 payload but not the length or content-type bounds)` | - |
| BT-REQ-1852 | The phone never uses on-device speech synthesis for a reply. | IMPLEMENTED-UNTESTED | `bounded: rg -n 'AVSpeechSynthesizer\|AVSpeechUtterance' ios/ returns nothing, 2026-08-24, pinned tree` | - |
| BT-REQ-1853 | One WKWebView hosts Familiar's shader page and exactly one surface claims it at a time. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarIslandController.swift:39 'func claim(_ surface: String) -> Bool {'; BoltrigTests/PhenotypeTests/testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive` | - |
| BT-REQ-1854 | State reaches the island as clamped, key-sorted v1 JSON, at most thirty times a second, only after the island has reported ready, and never twice with the same content. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarIslandController.swift:100 'guard let json = try? state.json(), json != lastSentJSON else { return }'; BoltrigTests/FamiliarBridgeTests/testStateEncodesSortedKeysAndClamps` | - |
| BT-REQ-1855 | The island message carries no text, identifier or secret: every field is a closed enum, a bounded number or a bounded number map. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarIslandBridge.swift:4 'Closed enums and bounded numbers only'; BoltrigTests/FamiliarBridgeTests/testStateEncodesSortedKeysAndClamps` | - |
| BT-REQ-1856 | The presence mode follows the web's precedence: error, then speaking, then listening, then working, then thinking, then standby. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarIslandBridge.swift:97 'static func mode(failed: Bool, speaking: Bool'; BoltrigTests/FamiliarBridgeTests/testModePrecedenceMatchesTheWeb` | - |
| BT-REQ-1857 | The island web view cancels any navigation that is not a file URL, and a missing page, a fallback report or a navigation failure falls back to the SwiftUI badge so the presence is never blank. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Familiar/FamiliarIslandController.swift:159 'if navigationAction.request.url?.isFileURL == true {' and :128 'isAvailable = false'; ios/Boltrig/Familiar/FamiliarPresenceView.swift:21 'private var hostsIsland: Bool {'` | - |
| BT-REQ-1858 | Familiar's phenotype is polled every three seconds only while a surface holds the island and the scene is active, and is dropped to nil otherwise. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarIslandController.swift:70 'guard let client = phenotypeSource, owner != nil, sceneActive else {'; BoltrigTests/PhenotypeTests/testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive` | - |
| BT-REQ-1859 | A phenotype reading that is not fresh yields no values, so Familiar wanders on her own rather than showing a stale mood. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Platform.swift:66 'values: fresh ? values : nil'; BoltrigTests/PhenotypeTests/testPhenotypeDecodesFreshAndRestingShapes` | - |
| BT-REQ-1860 | Only a genotype whose source is agent_capability.name.v1 binds a visual identity; anything else draws the neutral body, and unknown markings and accessories are dropped rather than guessed. | IMPLEMENTED | `ios/Boltrig/Familiar/FamiliarGenotype.swift:56 'guard let genotype, genotype.source == Self.boundSource else {'; BoltrigTests/FamiliarBridgeTests/testGenotypeIdentity` | - |
| BT-REQ-1861 | The bundled island page is byte-pinned to the worker source by a manifest and by make familiar-island-check inside worker-quality. | IMPLEMENTED | `apps/worker/scripts/sync-familiar-island.mjs:94 'if (!rebuilt.equals(committed)) {'; apps/worker/tests/familiarIsland.test.ts 'the committed Familiar island page'` | - |
| BT-REQ-1862 | First-run setup is four steps, Name, Provider, Image model and Ready, with no companion step and no voice step. | IMPLEMENTED | `ios/Boltrig/Session/OnboardingStore.swift:9 'case name, provider, vision, ready'; BoltrigTests/OnboardingTests/testNameStepValidatesBeforeMovingOn` | - |
| BT-REQ-1863 | The display name is normalised on the phone before it is sent: whitespace collapsed, one to eighty scalars, no control, format or surrogate characters. | IMPLEMENTED | `ios/Boltrig/Session/OnboardingStore.swift:167 'static func normalizedName(_ raw: String) -> String? {'; BoltrigTests/OnboardingTests/testNameRuleMatchesTheServer` | - |
| BT-REQ-1864 | Finishing setup writes the profile, then agent.character and setup.onboarding_version together, then announces adoption, in that order and exactly once even under concurrent presses. | IMPLEMENTED | `ios/Boltrig/Session/OnboardingStore.swift:129 'guard !finishInFlight else { return false }'; BoltrigTests/OnboardingTests/testFinishWritesProfileThenSettingsOnceUnderConcurrentPresses` | - |
| BT-REQ-1865 | A name the server refuses returns the person to the Name step with the plain sentence, and the settings are not written. | IMPLEMENTED | `ios/Boltrig/Session/OnboardingStore.swift:149 'reason == BoltrigError.displayNameReason'; BoltrigTests/OnboardingTests/testFinishReturnsToTheNameStepWhenTheServerRefusesTheName` | - |
| BT-REQ-1866 | Skipping the image model step submits no key and finishes setup. | IMPLEMENTED | `ios/Boltrig/Session/OnboardingStore.swift:120 'func skipVision() async {'; BoltrigTests/OnboardingTests/testSkipVisionFinishesWithoutSubmittingAKey` | - |
| BT-REQ-1867 | One press of Continue saves the provider key, answers an approval the server raised for the person's own submission, and reads back whether the provider answers. | IMPLEMENTED | `ios/Boltrig/Session/ProviderSetupStore.swift:118 'func complete() async -> Bool {'; BoltrigTests/ProviderSetupTests/testPendingHumanIsApprovedInTheSamePress` | - |
| BT-REQ-1868 | The key field is emptied before the first await, so nothing on screen holds a submitted key and a second press cannot resend it. | IMPLEMENTED | `ios/Boltrig/Session/ProviderSetupStore.swift:152 'apiKey = ""'; BoltrigTests/ProviderSetupTests/testProviderClearsTheKeyBeforeAwaitingAndSendsItOnce` | - |
| BT-REQ-1869 | A proposal that genuinely awaits an administrator is cached so the next press re-checks it instead of resubmitting the key, and any other dead proposal is dropped. | IMPLEMENTED | `ios/Boltrig/Session/ProviderSetupStore.swift:186 'case let .pending(next), let .pendingHuman(next):'; BoltrigTests/ProviderSetupTests/testAdministratorPendingIsCachedAndTheNextPressApprovesWithoutResubmitting and testDeadProposalIsDroppedWithTheServersSentence` | - |
| BT-REQ-1870 | An unreachable read-back after a save lets the step pass with an honest sentence, and only a server that positively reports the gateway is not ready holds the step. | IMPLEMENTED | `ios/Boltrig/Session/ProviderSetupStore.swift:238 'key.gatewayReady == false'; BoltrigTests/ProviderSetupTests/testUnreachableReReadPasses and testGatewayNotReadyHoldsTheStep` | - |
| BT-REQ-1871 | The three provider routes turn any server-explained refusal, on 4xx and on 503 alike, into an outcome whose sentence reaches the screen, while a refusal with no sentence is still thrown. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Onboarding.swift:45 'private func aiKeyOutcome(path: String, method: String, body: Data?)'; BoltrigTests/OnboardingTests/testClientTurnsServerSentencesIntoOutcomesAndThrowsTheRest` | - |
| BT-REQ-1872 | A typed provider address always wins, and a non-native provider with a published address submits it silently. | IMPLEMENTED | `ios/Boltrig/Session/ProviderSetupStore.swift:147 'baseURL: typedAddress.isEmpty ? rules.publishedBaseURL(trimmedProvider) : typedAddress'; BoltrigTests/ProviderSetupTests/testNonNativeProviderSubmitsItsPublishedAddress` | - |
| BT-REQ-1873 | The bundled provider catalogue is the web's models.dev snapshot byte for byte, decoded off the main thread with its revision pinned by a test, and a self-hosted Ollama entry is inserted immediately before Ollama Cloud with no models, an optional key and a required address. | IMPLEMENTED | `ios/Boltrig/Models/ProviderCatalogue.swift:30 'static let pinnedRevision =' and :142 'if id == "ollama-cloud" {'; BoltrigTests/OnboardingTests/testBundledCatalogueLoadsOffMainWithSelfHostedOllamaBeforeOllamaCloud` | - |
| BT-REQ-1874 | Settings offers eight destinations, searchable by their label and their one-line lead. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Views/Settings/SettingsPieces.swift:44 'static func matching(_ query: String) -> [SettingsDestination] {'` | - |
| BT-REQ-1875 | The approval posture is read-only on the phone, and the screen says a change needs a person signed in on the web. | IMPLEMENTED | `ios/Boltrig/Views/Settings/ApprovalsView.swift:39 'To change this, sign in on the web.'; BoltrigTests/AccountSettingsTests/testPostureIsReadAndNeverWritten` | - |
| BT-REQ-1876 | The server refuses a posture write from a personal access token, because the route requires an interactive credential class and a token resolves to kind pat. | IMPLEMENTED-UNTESTED | `boltrig/kernel/approval_posture_routes.py:25 'if p.actor_tier != "human" or not is_interactive_credential(p.credential_kind):'; boltrig/config/dev_posture.py:69 'INTERACTIVE_CREDENTIAL_KINDS = frozenset({"session", "federated", "dev-header"})'` | - |
| BT-REQ-1877 | Changing any appearance value writes all five appearance keys in one request, turning read-out replies on writes that one key, and either write rolls the local value back on failure. | IMPLEMENTED | `ios/Boltrig/Session/AccountSettingsStore.swift:42 'func saveAppearance(_ value: AppearanceSettings) async {' and :60 'try await client.putSettings(["voice.read_replies": value])'; BoltrigTests/AccountSettingsTests/testAppearanceWritesAllFiveKeysInOnePut, testAppearanceRollsBackWhenTheWriteFails, testReadRepliesRollsBackAndTellsNobodyWhenTheWriteFails` | - |
| BT-REQ-1878 | Security lists live sessions and live keys, marks the key this phone signs in with, and signs the phone out when that key is revoked. | IMPLEMENTED | `ios/Boltrig/Session/AccountSettingsStore.swift:132 'if let session, id == session.phoneTokenID {'; BoltrigTests/AccountSettingsTests/testTokensMarkThisPhoneAndRevokingItSignsOut` | - |
| BT-REQ-1879 | Health reads GET /readyz and treats a 503 as an answer carrying the report rather than a failure. | IMPLEMENTED | `ios/Boltrig/Networking/BoltrigClient+Account.swift:61 '\|\| http.statusCode == 503 else {'; BoltrigTests/AccountSettingsTests/testReadinessTolerates503AndMapsPlainLabels` | - |
| BT-REQ-1880 | Spending shows total cost and ceilings read-only, in money when a money ceiling exists and in usage otherwise. | IMPLEMENTED | `ios/Boltrig/Models/AccountModels.swift:141 'var spentLabel: String {'; BoltrigTests/AccountSettingsTests/testSpendingDecodesBudgetsAndCost` | - |
| BT-REQ-1881 | Archived chats lists only closed conversations, newest activity first, and can bring one back through POST /v1/me/conversations/{id}/restore. | IMPLEMENTED | `ios/Boltrig/Session/AccountSettingsStore.swift:80 '.filter { $0.status.lowercased() == "closed" }'; BoltrigTests/AccountSettingsTests/testArchivedIsTheClosedConversationsAndRestoreBringsOneBack` | - |
| BT-REQ-1882 | Deleting an account from the app is disabled and no deletion request of any kind reaches the network while the feature flag is false. | IMPLEMENTED | `ios/Boltrig/Support/BoltrigEnvironment.swift:29 'static let accountDeletionAvailable = false'; BoltrigTests/AccountSettingsTests/testDeleteAccountNeverReachesTheNetworkWhileUnavailable` | - |
| BT-REQ-1883 | The DELETE /v1/me route the deletion screen would call does not exist in the server tree. | SEAM | `bounded: rg -n 'delete("/v1/me"' boltrig/ returns nothing, 2026-08-24, pinned tree; boltrig/kernel/org_discovery_routes.py:29 '@app.get("/v1/me")' is the only /v1/me route` | - |
| BT-REQ-1884 | A debug-only preview workspace and a debug-only setup preview are reachable by launch arguments, compile out of every release build, and perform no network request. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Support/SetupPreview.swift:3 '#if DEBUG'; ios/Boltrig/App/BoltrigApp.swift:56 '#if DEBUG'; BoltrigTests/AccountSettingsTests/testPreviewStoreWritesNothingAndShowsEmptyStates` | - |
| BT-REQ-1885 | The test suite is ninety-five XCTest methods in twelve classes, every one except the live contract runs against an in-memory URLProtocol stub with no network, and two skip themselves rather than fail. | IMPLEMENTED | `ios/BoltrigTests/StubURLProtocol.swift:5 'final class StubURLProtocol: URLProtocol {'; ios/BoltrigTests/ClientAndParsingTests.swift:193 'throw XCTSkip("Keychain needs a signed host app'; ios/BoltrigTests/LiveContractTests.swift:22 'throw XCTSkip("no BOLTRIG_LIVE_EMAIL'` | - |
| BT-REQ-1886 | The live contract test signs in against a real instance, asserts the Familiar switch, performs the first-screen reads, sends one turn and signs out, and is skipped unless credentials are supplied. | IMPLEMENTED-UNTESTED | `ios/BoltrigTests/LiveContractTests.swift:29 'func testSignInAdoptionReadsAndOneChatTurnAgainstTheInstance() async throws {' (docs/HANDOVER-2026-08-22-ios-app.md:705 'run live; see "Blocked" below.')` | - |
| BT-REQ-1887 | No invariant in tests/invariants.yaml binds any iOS behaviour, and there is no UI test target, so every SwiftUI view in the app is unverified by any automated check. | IMPLEMENTED | `tests/invariants.yaml:3 'a one-line meaning plus the pytest node ids'; ios/Boltrig.xcodeproj/project.pbxproj:166 'targets = (' lists exactly two targets (bounded: rg -n 'XCUIApplication' ios/ returns nothing, 2026-08-24)` | - |
| BT-REQ-1888 | The app implements no push notifications, no universal links, no crash or error reporting, no live voice call, no background refresh and no offline copy of the record. | SEAM | `ios/README.md:102 'Push notifications, universal links, account deletion' (bounded: rg -n 'UNUserNotificationCenter\|registerForRemoteNotifications\|associated-domains\|BGTaskScheduler\|CoreData\|SwiftData' ios/ returns nothing, 2026-08-24)` | - |
| BT-REQ-1889 | Nothing but the credential and the chosen instance address survives a launch, so every screen is empty until the server answers. | IMPLEMENTED | `ios/Boltrig/Models/AuthModels.swift:145 'struct StoredSession: Codable, Equatable {'; BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken` | - |
| BT-REQ-1890 | The island contract declares bands, onset and genotype, and the application never produces any of the three. | DEAD | `ios/Boltrig/Familiar/FamiliarIslandBridge.swift:22 'var bands: [Double]? = nil' and :29 'var genotype: FamiliarGenotype? = nil'; ios/Boltrig/Familiar/FamiliarPresenceView.swift:68 'island.apply(FamiliarIslandState(' sets none of them (bounded: rg -n 'bands\|onset\|genotype' ios/Boltrig --glob '*.swift', 2026-08-24)` | - |
| BT-REQ-1891 | The badge's bound-genotype rendering, four body shapes, four markings and three accessories, is unreachable from any application call site and is exercised only by a unit test. | DEAD | `ios/Boltrig/Familiar/FamiliarBadgeView.swift:8 'var identity: FamiliarVisualIdentity = .neutral' (bounded: rg -n 'FamiliarBadgeView(' ios/ gives TodayView.swift:178 and FamiliarPresenceView.swift:39, neither passing identity, 2026-08-24)` | - |
| BT-REQ-1892 | Stored message run ids, HITL request ids, stored attachments and queued message ids are decoded from history and never rendered. | DEAD | `ios/Boltrig/Session/ChatSession.swift:126 '.map { ChatMessage(id: UUID(), role: $0.role == .user ? .user : .assistant, content: $0.content, createdAt: Date()) }' drops every other field (bounded: rg -n 'queuedMessageIDs\|hitlRequestID' ios/Boltrig/ matches only ChatHistoryModels.swift)` | - |
| BT-REQ-1893 | The model-readable media types the server publishes are decoded and never used, while the composer's footnote about which files are read is a hard-coded sentence. | DEAD | `ios/Boltrig/Session/ChatSession.swift:34 'Only text files are read.' (bounded: rg -n 'readableTypes' ios/ matches only the declaration and the decode, 2026-08-24)` | - |
| BT-REQ-1894 | The session-reason 'not authenticated' in the client's 401 classifier matches nothing the server emits. | DEAD | `ios/Boltrig/Networking/BoltrigClient.swift:292 '"invalid or expired access token", "not authenticated", "unauthorized",' (bounded: rg -ni 'not authenticated' boltrig/ returns nothing, 2026-08-24)` | - |
| BT-REQ-1895 | The client's native-provider set and alias table are a third copy of the kernel's authority with no gate keeping them equal. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Models/ProviderCatalogue.swift:49 'static let bifrostSupported: Set<String> = ['; boltrig/identity/bifrost_user_admin.py:21 'BIFROST_PROVIDERS = frozenset(' (bounded: only apps/worker/tests/providerCatalogue.test.ts parses the Python, and it checks the TypeScript copy)` | - |
| BT-REQ-1896 | Familiar's per-provider fallback voice ids are a second copy of the character bundle with no gate keeping them equal. | IMPLEMENTED-UNTESTED | `ios/Boltrig/Speech/SpeechResolution.swift:14 '"fish": "c8f64deb39914cfca7f47ccfc3bca82f",'; apps/worker/src/bundles/familiar/character.json:63 '"fish": "c8f64deb39914cfca7f47ccfc3bca82f",'` | - |
| BT-REQ-1897 | Three public links shipped in Settings point at pages that do not exist. | SCAFFOLDED | `ios/Boltrig/Support/BoltrigEnvironment.swift:12 'These pages do not exist on boltrig.ai yet'` | - |
| BT-REQ-1898 | The default instance is the development preview host, and moving it silently signs out every installed copy at the next launch. | IMPLEMENTED | `ios/Boltrig/Support/BoltrigEnvironment.swift:10 'URL(string: "https://dev.boltrig.ai")!'; BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken proves the discard` | - |

**Status counts**: DEAD 5, IMPLEMENTED 70, IMPLEMENTED-UNTESTED 21, SCAFFOLDED 1, SEAM 2.

**Every row's invariant column is `-`.** `tests/invariants.yaml` binds pytest node ids and
nothing else, so no `K-*`, `P*`, `SEC*` or `FR*` id can bind an XCTest method (10.3). The
security-bearing rows here, in particular those covering the Keychain, the bearer credential,
the CSRF header, the https-only instance rule and the token's scope, are therefore unbound.
That is recorded as RISK-1801 and RISK-1804.

---

## 13. Requirements table

Ids run `BT-REQ-1800` to `BT-REQ-1899`. Every row is grounded in a section above.

**On the statuses in this table.** `IMPLEMENTED` is used only where both halves are
nameable: a reachable entrypoint AND a test method that exercises it. Where a code path is
reachable and no test was found, the row says `IMPLEMENTED-UNTESTED` and the evidence cell
says where the search ran. The bound of that search is the same everywhere unless a row
narrows it: the twelve XCTest classes in `ios/BoltrigTests/`, read in full, 2026-08-24,
pinned tree. Two whole categories are untestable here rather than untested: every SwiftUI
view, because there is no `XCUITest` target (10.3), and every build setting, because no gate
reads the project file (8.1).

**The invariant column is `-` on every row, and that is a finding, not an omission.**
`tests/invariants.yaml` binds pytest node ids only; an XCTest method has no representation
in it, so no requirement in this area can be bound (10.3). The authoring contract calls an
unbound security or correctness requirement a finding in its own right; the whole set is
recorded as RISK-1801, and BT-REQ-1889 records the related fact that no test run exists
for the pinned tree at all.

| id | statement | status | evidence | invariant |
| --- | --- | --- | --- | --- |
| BT-REQ-1800 | No container image copies `ios/`, so a kernel, fleet or worker roll never ships the phone app. | IMPLEMENTED-UNTESTED | [`deploy/kernel.Dockerfile:158`](../../../deploy/kernel.Dockerfile) `"COPY boltrig/ /app/boltrig/"`; no gate asserts it (bounded: `grep -n 'COPY'` over the four Dockerfiles, 2026-08-24, pinned tree) | - |
| BT-REQ-1801 | The application and test targets link no third-party package: both declare an empty `packageProductDependencies` and an empty Frameworks phase. | IMPLEMENTED-UNTESTED | [`ios/Boltrig.xcodeproj/project.pbxproj:105`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"packageProductDependencies = ("`; nothing in `.github/` or the Makefile reads the project file | - |
| BT-REQ-1802 | Keychain access is confined to `Keychain` with `KeychainSessionVault` as its only production caller, and every `URLRequest` is built by `BoltrigClient.makeRequest`. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionVault.swift:19`](../../../ios/Boltrig/Session/SessionVault.swift) `"guard let data = try Keychain.data(for: account) else { return nil }"`; [`ios/Boltrig/Networking/BoltrigClient.swift:172`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"func makeRequest(path: String, method: String, body: Data?"`; bounded: `rg -n 'URLRequest' ios/Boltrig/Views/ ios/Boltrig/App/` returns nothing, 2026-08-24. No lint rule enforces either confinement | - |
| BT-REQ-1803 | The account's stored companion id is reduced to three cases and the id itself is never rendered. | IMPLEMENTED | [`ios/Boltrig/Models/CompanionPresence.swift:18`](../../../ios/Boltrig/Models/CompanionPresence.swift) `"self = characterID == Self.familiarID ? .familiar : .other"`; `BoltrigTests/ClientAndParsingTests/testAccountDecodingReadsTheSettingsBag` | - |
| BT-REQ-1804 | The debug preview workspace and the whole stub server are fenced by `#if DEBUG` and compile into no Release build. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Support/SetupPreview.swift:3`](../../../ios/Boltrig/Support/SetupPreview.swift) `"#if DEBUG"`; no test builds a Release configuration, and no gate does either | - |
| BT-REQ-1805 | The app is iPhone-only and portrait-only on an iOS 17.0 floor, and its bundle identifier is also the Keychain service name and the unified-log subsystem. | IMPLEMENTED-UNTESTED | [`ios/Boltrig.xcodeproj/project.pbxproj:362`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"TARGETED_DEVICE_FAMILY = 1;"`; [`ios/Boltrig/Support/Keychain.swift:12`](../../../ios/Boltrig/Support/Keychain.swift) `"static let service = \"ai.boltrig.app\""`; no test compares the three names and no gate reads build settings | - |
| BT-REQ-1806 | The whole persisted state of a signed-in phone is one `StoredSession` held as JSON in a single Keychain generic-password item. | IMPLEMENTED | [`ios/Boltrig/Models/AuthModels.swift:145`](../../../ios/Boltrig/Models/AuthModels.swift) `"struct StoredSession: Codable, Equatable {"`; `BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount` | - |
| BT-REQ-1807 | The Keychain item is written with `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly`, so an encrypted backup restored onto another phone carries no session. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Support/Keychain.swift:27`](../../../ios/Boltrig/Support/Keychain.swift) `"kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly,"`; `ClientAndParsingTests/testKeychainRoundTrip` covers set, read and remove and asserts no accessibility attribute | - |
| BT-REQ-1808 | `UserDefaults` holds the chosen instance URL and nothing else, only while it differs from the hosted default, and every `URLSession` is built from an ephemeral configuration. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Support/BoltrigEnvironment.swift:71`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"if let url, url != BoltrigEnvironment.hostedInstanceURL {"`; [`ios/Boltrig/Session/SessionStore.swift:40`](../../../ios/Boltrig/Session/SessionStore.swift) `"configuration: URLSessionConfiguration = .ephemeral"`; `BoltrigTests/SessionStoreTests/testChangingInstancePersistsAndSignsOut` covers the defaults half only | - |
| BT-REQ-1809 | The token client refuses cookies outright, with `httpShouldSetCookies` false and an accept policy of never. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:330`](../../../ios/Boltrig/Session/SessionStore.swift) `"config.httpShouldSetCookies = false"`; no test in `ios/BoltrigTests/` inspects the token session's configuration | - |
| BT-REQ-1810 | The island web view uses a non-persistent website data store, so the shader page writes nothing to disk. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:112`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"configuration.websiteDataStore = .nonPersistent()"`; `PhenotypeTests` builds a controller and never asserts its web view configuration | - |
| BT-REQ-1811 | An instance address is accepted only over https and is canonicalised to host and port, with path, query, fragment, user and password stripped. | IMPLEMENTED | [`ios/Boltrig/Support/BoltrigEnvironment.swift:52`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"components.scheme?.lowercased() == \"https\" else { return nil }"`; `BoltrigTests/ClientAndParsingTests/testInstanceAddressParsing` | - |
| BT-REQ-1812 | Restore makes no network call at all unless a stored session exists and its instance matches the current one. | IMPLEMENTED | [`ios/Boltrig/Session/SessionStore.swift:75`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard stored.instanceURL == instanceURL else {"`; `BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken` asserts `StubURLProtocol.requests.isEmpty` | - |
| BT-REQ-1813 | Restore fails three ways: 401 or 403 clears the vault and signs out, unreachable or 5xx keeps the token and shows the unreachable screen, and anything else clears the vault and shows the message. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:86`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .unauthenticated, .forbidden:"`; `BoltrigTests/SessionStoreTests/testRestoreWithARevokedTokenSignsOut` and `testRestoreWhileOfflineKeepsTheToken`. The fourth arm, a throw that is not a `BoltrigError`, is untested | - |
| BT-REQ-1814 | The root view renders from `SessionStore.State` alone, and a signed-in account goes to first-run setup until `setup.onboarding_version` reaches 1. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/App/BoltrigApp.swift:24`](../../../ios/Boltrig/App/BoltrigApp.swift) `"account.onboardingComplete ? .workspace : .onboarding"`; `BoltrigTests/OnboardingTests/testRootDestinationResolve`. The rendering half is untestable here: there is no UI test target | - |
| BT-REQ-1815 | Sign-in refuses an empty email or password locally, and `decodeSignIn` maps exactly four server statuses and throws on anything else. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Networking/BoltrigClient.swift:230`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"static func decodeSignIn(_ data: Data) throws -> SignInOutcome {"`; `BoltrigTests/ClientAndParsingTests/testSignInOutcomeDecoding`. No test submits an empty field | - |
| BT-REQ-1816 | A 401 whose reason is not one of the five session reasons becomes a rejection, so the server's own sentence reaches the person. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient.swift:269`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"if let reason, !sessionReasons.contains(reason) {"`; `BoltrigTests/SessionStoreTests/testWrongPasswordStaysSignedOutWithPlainCopy` | - |
| BT-REQ-1817 | Two-step verification and two-step enrolment run on the same cookie session, no token is minted or stored until the ceremony passes, and the recovery codes are held only in the state enum. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:178`](../../../ios/Boltrig/Session/SessionStore.swift) `"self.state = .recoveryCodes(csrfToken: csrfToken, codes: enrolment.recoveryCodes)"`; `BoltrigTests/SessionStoreTests/testTwoFactorRequiredAsksForTheCodeThenSignsIn` asserts the vault is empty at the challenge. The enrolment calls themselves are untested | - |
| BT-REQ-1818 | A forced password change is checked locally for twelve characters and a matching confirmation before anything leaves the phone. | IMPLEMENTED | [`ios/Boltrig/Session/SessionStore.swift:142`](../../../ios/Boltrig/Session/SessionStore.swift) `"guard new.count >= 12 else {"`; `BoltrigTests/SessionStoreTests/testForcedPasswordChangeIsCompletedBeforeTheTokenIsMinted` | - |
| BT-REQ-1819 | Finishing sign-in mints the token, saves it, closes the cookie session and reads the account in that order, and a mint answer without a non-empty secret throws rather than storing a blank credential. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:283`](../../../ios/Boltrig/Session/SessionStore.swift) `"let minted = try await sessionClient.mintAccessToken(name: Self.tokenName()"`; `BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount`. The empty-secret branch at [`ios/Boltrig/Networking/BoltrigClient.swift:73`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"let secret = object[\"secret\"] as? String, !secret.isEmpty else {"` is untested | - |
| BT-REQ-1820 | The phone asks for a 90-day token and names it after the device and the sign-in date in `en_US_POSIX`, so it is recognisable in the web token list. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Support/BoltrigEnvironment.swift:24`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"static let accessTokenLifetimeDays = 90"`; `BoltrigTests/SessionStoreTests/testSignInMintsAPhoneTokenAndLoadsTheAccount`. `SessionStore.tokenName` itself is called by no test | - |
| BT-REQ-1821 | A password-change or enrolment clamp the server still holds during the mint call routes back into the ceremony rather than out of it. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:292`](../../../ios/Boltrig/Session/SessionStore.swift) `"case .passwordChangeRequired:"`; the tests reach those states from the login answer only, never from a 403 on the mint route | - |
| BT-REQ-1822 | The password-reset screen never reveals whether an account exists: the success copy is non-committal. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:198`](../../../ios/Boltrig/Session/SessionStore.swift) `"If that account can be recovered, reset instructions are on their way"`; no test in `ios/BoltrigTests/` calls `requestPasswordReset` | - |
| BT-REQ-1823 | Changing instance signs out, clears the vault and persists the new address, because a token belongs to one instance. | IMPLEMENTED | [`ios/Boltrig/Session/SessionStore.swift:222`](../../../ios/Boltrig/Session/SessionStore.swift) `"func useInstance(_ url: URL) async {"`; `BoltrigTests/SessionStoreTests/testChangingInstancePersistsAndSignsOut` | - |
| BT-REQ-1824 | An account whose companion is unset or is another character is switched to Familiar once, and the adopted announcement is sent only after the settings write succeeds. | IMPLEMENTED | [`ios/Boltrig/Session/SessionStore.swift:246`](../../../ios/Boltrig/Session/SessionStore.swift) `"try await client.putSettings([\"agent.character\": CompanionPresence.familiarID])"`; `BoltrigTests/SessionStoreTests/testAnotherCompanionIsSwitchedToFamiliarOnFirstLoad` asserts the ordering | - |
| BT-REQ-1825 | A failed adoption write reports one plain sentence, returns the original account and still signs the person in. | IMPLEMENTED | [`ios/Boltrig/Session/SessionStore.swift:254`](../../../ios/Boltrig/Session/SessionStore.swift) `"familiarAdoptedNotice = \"Boltrig could not set Familiar as your companion. It will try again next time.\""`; `BoltrigTests/SessionStoreTests/testFailedAdoptionWriteSaysSoAndStillSignsIn` | - |
| BT-REQ-1826 | Today loads once per workspace, fetching approvals and conversations concurrently, filtering closed conversations out, and setting `loadError` when either read fails. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/AppStore.swift:66`](../../../ios/Boltrig/Session/AppStore.swift) `"guard !loadedOnce else { return }"`; [`ios/Boltrig/Session/AppStore.swift:104`](../../../ios/Boltrig/Session/AppStore.swift) `"loadError = (error as? BoltrigError)?.errorDescription"`; `BoltrigTests/ReplySpeakerTests/testWorkspaceWiresTheSpeakerIntoTheChat` covers the load-once half; no test asserts the closed filter or `loadError` | - |
| BT-REQ-1827 | Failing to read the linked computers is not an error: the rest of Today still renders. | IMPLEMENTED | [`ios/Boltrig/Session/AppStore.swift:102`](../../../ios/Boltrig/Session/AppStore.swift) `"if let linked = try? await client.devices() { devices = linked.filter { $0.revokedAt == nil } }"`; `BoltrigTests/LinkedDeviceTests/testDevicesFailureLeavesTheRestOfTodayIntact` | - |
| BT-REQ-1828 | The phone posts an approval decision and removes the row only when the server accepts it, but whether the server accepts a decision carried by the phone's credential class at all is not settled here. | UNCERTAIN | [`ios/Boltrig/Session/AppStore.swift:148`](../../../ios/Boltrig/Session/AppStore.swift) `"approvals.removeAll { $0.id == approval.id }"`; the sole-author relief is gated on an interactive credential kind and a PAT is not one, [`boltrig/config/dev_posture.py:69`](../../../boltrig/config/dev_posture.py) `"INTERACTIVE_CREDENTIAL_KINDS = frozenset({\"session\", \"federated\", \"dev-header\"})"`. What would settle it: read `boltrig/kernel/hitl_response_auth.py` end to end, or run the live contract test with a pending approval. See OQ-1802 | - |
| BT-REQ-1829 | Whether a conversation is working is the server's own flag and is never inferred on the phone. | IMPLEMENTED | [`ios/Boltrig/Models/AppModels.swift:11`](../../../ios/Boltrig/Models/AppModels.swift) `"struct ConversationSummary: Identifiable, Codable, Hashable {"`; `BoltrigTests/ClientAndParsingTests/testConversationsDecodeTheServerShape` | - |
| BT-REQ-1830 | A linked computer reads as on only when the server says online and its last-seen time is within 20 seconds, and disconnecting one revokes it on the server before dropping it from the list. | IMPLEMENTED | [`ios/Boltrig/Models/LinkedDevice.swift:24`](../../../ios/Boltrig/Models/LinkedDevice.swift) `"guard revokedAt == nil, presence == \"online\", let lastSeenAt else { return false }"`; `BoltrigTests/LinkedDeviceTests/testDevicesDecodeAndLivenessIsReadFromLastSeen` and `testRefreshLoadsTheLinkedComputersAndDisconnectRevokes` | - |
| BT-REQ-1831 | A turn that ends with something waiting posts `.boltrigNeedsYou`, which Today observes and refreshes on. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/AppStore.swift:156`](../../../ios/Boltrig/Session/AppStore.swift) `"needsYouObserver = NotificationCenter.default.addObserver(forName: .boltrigNeedsYou"`; no test in `ios/BoltrigTests/` posts or observes that notification | - |
| BT-REQ-1832 | A chat turn posts `message`, `origin: "ios"`, a fresh idempotency key, the attachments and the conversation id when one is open; a 202 yields exactly one queued event and a non-2xx throws a mapped error into the stream. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient.swift:132`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"\"origin\": \"ios\","`; `BoltrigTests/ClientAndParsingTests/testStreamChatYieldsEventsInOrder`, `testStreamChatReportsAQueuedTurn`, `testStreamChatSurfacesAnHTTPFailureBeforeTheStream` | - |
| BT-REQ-1833 | The event stream is split into lines by hand, because `AsyncBytes.lines` does not deliver the blank line that ends a frame, and a trailing carriage return is stripped. | IMPLEMENTED | [`ios/Boltrig/Networking/SSEByteReader.swift:16`](../../../ios/Boltrig/Networking/SSEByteReader.swift) `"if lineBuffer.last == UInt8(ascii: \"\\r\") { lineBuffer.removeLast() }"`; `BoltrigTests/ClientAndParsingTests/testStreamChatYieldsEventsInOrder` | - |
| BT-REQ-1834 | A frame that is not JSON becomes a synthetic `malformed_event`, and an unmapped event type becomes `.other`, so neither fails the turn. | IMPLEMENTED | [`ios/Boltrig/Networking/ChatEvent.swift:119`](../../../ios/Boltrig/Networking/ChatEvent.swift) `"return [\"type\": \"malformed_event\"]"`; `BoltrigTests/ClientAndParsingTests/testSSEParserJoinsDataLinesAndIgnoresOtherFields` and `testChatEventMapping` | - |
| BT-REQ-1835 | Eleven event cases are folded to no visible change by name rather than by a default, and a turn that ends with no text but a reason writes the reason as the assistant message and sets `turnFailed`. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/ChatSession.swift:321`](../../../ios/Boltrig/Session/ChatSession.swift) `"case .messageEnd, .steerConsumed, .reasoningDelta, .heartbeat, .subagentEnd,"`; [`ios/Boltrig/Session/ChatSession.swift:332`](../../../ios/Boltrig/Session/ChatSession.swift) `"} else if let reason {"`; `ChatSessionTests` covers history, follow and stop, and feeds neither branch | - |
| BT-REQ-1836 | A 413 on a chat turn is replaced by one fixed sentence about the attachments. | IMPLEMENTED | [`ios/Boltrig/Session/ChatSession.swift:181`](../../../ios/Boltrig/Session/ChatSession.swift) `"if (error as? BoltrigError)?.status == 413 { copy = Self.attachmentsRejectedCopy }"`; `BoltrigTests/AttachmentTests/testARejectedUploadShowsPlainCopy` | - |
| BT-REQ-1837 | Stopping a turn cancels the local task and asks the server to cancel the run best effort, while opening another conversation stops the turn without cancelling anything. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/ChatSession.swift:237`](../../../ios/Boltrig/Session/ChatSession.swift) `"Task { try? await client.cancelRun(id: runID) }"`; `BoltrigTests/ChatSessionTests/testStopPostsTheCancelForTheLiveRun`. The `cancelOnServer: false` path is untested | - |
| BT-REQ-1838 | History keeps only messages that are neither superseded nor of an unknown role, and a run the server still calls active is followed from cursor 0 on the first load only. | IMPLEMENTED | [`ios/Boltrig/Session/ChatSession.swift:125`](../../../ios/Boltrig/Session/ChatSession.swift) `".filter { $0.supersededBy == nil && $0.role != .other }"`; `BoltrigTests/ChatSessionTests/testHistoryDecodesTheServerShapeAndHidesSupersededMessages` and `testActiveRunIsFollowedFromZeroThenHistoryReloads` | - |
| BT-REQ-1839 | A 409 from the follow route is not an error: it yields idle, clears the active run and finishes. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient+Chat.swift:41`](../../../ios/Boltrig/Networking/BoltrigClient+Chat.swift) `"if http.statusCode == 409 {"`; `BoltrigTests/ChatSessionTests/testFollowIdleIsNotAnError` | - |
| BT-REQ-1840 | The history reload that follows a reconnect never re-follows, so a stale `active_run_id` cannot loop. | IMPLEMENTED | [`ios/Boltrig/Session/ChatSession.swift:222`](../../../ios/Boltrig/Session/ChatSession.swift) `"await loadHistory(followActiveRun: false)"`; `BoltrigTests/ChatSessionTests/testStaleActiveRunWithAnIdleFollowDoesNotLoop` asserts one events call and two history calls | - |
| BT-REQ-1841 | A truncated replay raises one honest notice rather than presenting a partial record as complete. | IMPLEMENTED | [`ios/Boltrig/Session/ChatSession.swift:208`](../../../ios/Boltrig/Session/ChatSession.swift) `"self.notice = \"Earlier live activity is not shown. The full record appears when the turn settles.\""`; `BoltrigTests/ChatSessionTests/testFollowFramesCarryCursorsAndTruncation` | - |
| BT-REQ-1842 | Returning to the foreground reconnects only when a run is known live and nothing else is in flight, and a reply that arrives through a reconnect is committed to the thread but never handed to the speaker. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/ChatSession.swift:226`](../../../ios/Boltrig/Session/ChatSession.swift) `"guard activeRunID != nil, !isSending, !isReconnecting else { return }"`; [`ios/Boltrig/Session/ChatSession.swift:345`](../../../ios/Boltrig/Session/ChatSession.swift) `"private func finishReconnect() {"` calls no turn-ended handler; no test in `ios/BoltrigTests/` calls `reconnectIfRunning`, and `ReplySpeakerTests` never drives a reconnect | - |
| BT-REQ-1843 | A chosen file is size-checked from its resource values before its bytes are read and again after, and a photo is re-encoded at three qualities then shrunk by 0.7 on the long side up to ten times, stopping at 160 px. | IMPLEMENTED | [`ios/Boltrig/Support/AttachmentImporter.swift:17`](../../../ios/Boltrig/Support/AttachmentImporter.swift) `"let size = (try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? Int.max"`; `BoltrigTests/AttachmentTests/testAFileOverTheLimitIsRefusedBeforeItIsRead`, `testAPhotoOverTheLimitIsShrunkToFit`, `testAPhotoThatCannotFitIsRefusedWithTheSizeCopy` | - |
| BT-REQ-1844 | Three attachment limits are applied in order, count then per-file size then total size, each with its own sentence, and the code defaults of 8 files, 256 KiB each and 1 MiB total apply when `GET /v1/chat/config` cannot be read. | IMPLEMENTED | [`ios/Boltrig/Session/ChatSession.swift:258`](../../../ios/Boltrig/Session/ChatSession.swift) `"if attachments.count >= limits.maxCount {"`; `BoltrigTests/ChatSessionTests/testAttachmentLimitsAreEnforcedWithPlainCopy` and `testAttachmentLimitsDefaultWhenConfigIsUnreadable` | - |
| BT-REQ-1845 | Attachment bytes travel base64 inside the chat JSON body as name, media type and data. | IMPLEMENTED | [`ios/Boltrig/Models/ChatHistoryModels.swift:79`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"[\"name\": name, \"media_type\": mediaType, \"data\": data.base64EncodedString()]"`; `BoltrigTests/ClientAndParsingTests/testStreamChatYieldsEventsInOrder` | - |
| BT-REQ-1846 | Reading replies aloud requires the account setting, a bound `voice.speak` adapter and a voice id together, and a person's override applies only to `pocket-voice` and only when it matches the id pattern. | IMPLEMENTED | [`ios/Boltrig/Speech/SpeechResolution.swift:24`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"var canSpeak: Bool { enabled && provider != nil && voiceID != nil }"`; `BoltrigTests/ReplySpeakerTests/testResolutionFollowsTheSettingTheProviderAndTheVoiceRules` | - |
| BT-REQ-1847 | The phone never uses the device's own speech synthesiser: audio always comes from the server through `voice.speak`. | IMPLEMENTED | [`ios/Boltrig/Speech/ReplySpeaker.swift:50`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"let outcome = try await client.invoke(noun: \"voice\", verb: SpeechResolution.speakVerb"`; bounded: `rg -n 'AVSpeechSynthesizer' ios/` and `rg -n 'AVSpeechUtterance' ios/` both return nothing, 2026-08-24; `BoltrigTests/ReplySpeakerTests/testSpeaksOncePerRunWithTheExactRequest` | - |
| BT-REQ-1848 | One reply is spoken per run id, and the answer is accepted only when the invoke returned ok, the base64 is at most 12,000,000 characters and the content type begins with `audio/`. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Speech/ReplySpeaker.swift:43`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"guard !spokenRuns.contains(runID) else { return }"`; `BoltrigTests/ReplySpeakerTests/testSpeaksOncePerRunWithTheExactRequest`. The payload bounds at [`ios/Boltrig/Speech/ReplySpeaker.swift:53`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"let encoded = output[\"audio_b64\"] as? String, encoded.count <= Self.maxAudioBase64,"` are exercised by no oversized or wrongly typed fixture | - |
| BT-REQ-1849 | Every speech failure is silent by design, and a late answer from a superseded request is dropped by a generation counter. | IMPLEMENTED | [`ios/Boltrig/Speech/ReplySpeaker.swift:60`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"// Silent by design: no audio is not an error the person needs to see."`; `BoltrigTests/ReplySpeakerTests/testFailuresAreSilent` and `testStopEndsSpeechAndANewTurnStopsTheOldOne` | - |
| BT-REQ-1850 | Playback runs on a spoken-audio session that ducks other audio and is deactivated with `notifyOthersOnDeactivation` when it ends. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Speech/ReplySpeaker.swift:113`](../../../ios/Boltrig/Speech/ReplySpeaker.swift) `"try session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])"`; the tests inject a fake player, so `SystemAudioPlayer` is exercised by nothing (bounded: `rg -n 'SystemAudioPlayer' ios/BoltrigTests/` returns nothing, 2026-08-24) | - |
| BT-REQ-1851 | The spoken text is markdown reduced by ten ordered rules and capped at 15,000 characters. | IMPLEMENTED | [`ios/Boltrig/Speech/SpeechResolution.swift:63`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"return String(text.prefix(maxSpokenCharacters))"`; `BoltrigTests/ReplySpeakerTests/testSpeechTextReducesMarkdownLikeTheWeb` | - |
| BT-REQ-1852 | Only one surface holds the island at a time, and the first claim is what creates the web view. | IMPLEMENTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:39`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"func claim(_ surface: String) -> Bool {"`; `BoltrigTests/PhenotypeTests/testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive` | - |
| BT-REQ-1853 | The phenotype poll runs every three seconds and only while a surface holds the island and the scene is active; otherwise the island is handed nothing and Familiar wanders on her own. | IMPLEMENTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:70`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"guard let client = phenotypeSource, owner != nil, sceneActive else {"`; `BoltrigTests/PhenotypeTests/testPollRunsOnlyWhileASurfaceHoldsTheIslandAndTheSceneIsActive` | - |
| BT-REQ-1854 | Island state is queued and sent at most thirty times a second, only after the island reports ready, and an identical JSON is not re-sent. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:100`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"guard let json = try? state.json(), json != lastSentJSON else { return }"`; no test in `ios/BoltrigTests/` drives `apply` or the controller's `flush` (bounded: `rg -n 'flush' ios/BoltrigTests/` matches only the SSE parser, 2026-08-24) | - |
| BT-REQ-1855 | Island state carries no text, identifier or secret, is clamped to its contract before it is sent, and encodes with sorted keys so two equal states are byte-identical. | IMPLEMENTED | [`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:32`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"func clamped() -> FamiliarIslandState {"`; [`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:51`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"encoder.outputFormatting = [.sortedKeys]"`; `BoltrigTests/FamiliarBridgeTests/testStateEncodesSortedKeysAndClamps` | - |
| BT-REQ-1856 | Familiar's mode follows the fixed precedence error, speaking, listening, working, thinking, standby. | IMPLEMENTED | [`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:97`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"static func mode(failed: Bool, speaking: Bool, listening: Bool, streaming: Bool, loading: Bool)"`; `BoltrigTests/FamiliarBridgeTests/testModePrecedenceMatchesTheWeb` | - |
| BT-REQ-1857 | The island answers with four report types plus an unknown case, and an unrecognised report changes nothing. | IMPLEMENTED | [`ios/Boltrig/Familiar/FamiliarIslandBridge.swift:62`](../../../ios/Boltrig/Familiar/FamiliarIslandBridge.swift) `"enum FamiliarIslandReport: Equatable {"`; `BoltrigTests/FamiliarBridgeTests/testReportsDecode` | - |
| BT-REQ-1858 | A missing island page turns the badge on permanently, a dead web content process is reloaded with `isReady` dropped, and at most twenty reports are kept and logged to the `ai.boltrig.app` subsystem as public. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:128`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"isAvailable = false"`; [`ios/Boltrig/Familiar/FamiliarIslandController.swift:136`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"if reports.count > 20 { reports.removeFirst() }"`; no test removes the bundled page, names `webViewWebContentProcessDidTerminate`, or calls `receive` | - |
| BT-REQ-1859 | The presence attaches the web view as soon as its surface holds the island, fades it in only when ready and shows the badge until then, and forces a minimised presentation with a device-pixel cap of at most 2 while the scene is inactive. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarPresenceView.swift:21`](../../../ios/Boltrig/Familiar/FamiliarPresenceView.swift) `"private var hostsIsland: Bool {"`; [`ios/Boltrig/Familiar/FamiliarPresenceView.swift:71`](../../../ios/Boltrig/Familiar/FamiliarPresenceView.swift) `"presentation: active ? presentation : .minimised,"`; there is no UI test target (bounded: `rg -n 'XCUIApplication' ios/` returns nothing, 2026-08-24) | - |
| BT-REQ-1860 | First-run setup has four steps, name, provider, image model and ready, with no companion step and no voice step, and an account that already has a display name starts at the provider step. | IMPLEMENTED | [`ios/Boltrig/Session/OnboardingStore.swift:10`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"case name, provider, vision, ready"`; [`ios/Boltrig/Session/OnboardingStore.swift:66`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"account.displayName.isEmpty ? .name : .provider"`; `BoltrigTests/OnboardingTests/testNameStepValidatesBeforeMovingOn` | - |
| BT-REQ-1861 | A display name is normalised to the server's rule before it is sent: whitespace collapsed, 1 to 80 scalars, no control, format or surrogate characters. | IMPLEMENTED | [`ios/Boltrig/Session/OnboardingStore.swift:167`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"static func normalizedName(_ raw: String) -> String? {"`; `BoltrigTests/OnboardingTests/testNameRuleMatchesTheServer` | - |
| BT-REQ-1862 | Finishing setup writes the profile then the two settings, in that order and exactly once under concurrent presses, and a name the server refuses returns the person to the name step with the settings unwritten. | IMPLEMENTED | [`ios/Boltrig/Session/OnboardingStore.swift:129`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"guard !finishInFlight else { return false }"`; `BoltrigTests/OnboardingTests/testFinishWritesProfileThenSettingsOnceUnderConcurrentPresses` and `testFinishReturnsToTheNameStepWhenTheServerRefusesTheName` | - |
| BT-REQ-1863 | Skipping the image model finishes setup without submitting anything. | IMPLEMENTED | [`ios/Boltrig/Session/OnboardingStore.swift:121`](../../../ios/Boltrig/Session/OnboardingStore.swift) `"func skipVision() async {"`; `BoltrigTests/OnboardingTests/testSkipVisionFinishesWithoutSubmittingAKey` | - |
| BT-REQ-1864 | The provider key field is emptied before the first `await`, so nothing on screen holds the key once it is sent and a second press cannot resend it. | IMPLEMENTED | [`ios/Boltrig/Session/ProviderSetupStore.swift:152`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"apiKey = \"\""`; `BoltrigTests/ProviderSetupTests/testProviderClearsTheKeyBeforeAwaitingAndSendsItOnce` reads the field from inside the stub handler | - |
| BT-REQ-1865 | An approval the server raised for the person's own submission is answered in the same press, a proposal that belongs to an administrator is cached so the next press re-checks it rather than resubmitting the key, and any other outcome drops the proposal. | IMPLEMENTED | [`ios/Boltrig/Session/ProviderSetupStore.swift:186`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"case let .pending(next), let .pendingHuman(next):"`; `BoltrigTests/ProviderSetupTests/testPendingHumanIsApprovedInTheSamePress`, `testAdministratorPendingIsCachedAndTheNextPressApprovesWithoutResubmitting`, `testDeadProposalIsDroppedWithTheServersSentence` | - |
| BT-REQ-1866 | An unreachable gateway read-back passes the provider step and only a positive `gateway_ready == false` holds it, so not knowing and knowing it is broken are different answers. | IMPLEMENTED | [`ios/Boltrig/Session/ProviderSetupStore.swift:233`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"guard let refreshed = try? await client.aiKeys() else {"`; `BoltrigTests/ProviderSetupTests/testUnreachableReReadPasses` and `testGatewayNotReadyHoldsTheStep` | - |
| BT-REQ-1867 | A typed provider address always wins and a non-native provider with none submits the catalogue's published address, while a missing model, address or required key refuses locally and sends nothing. | IMPLEMENTED | [`ios/Boltrig/Session/ProviderSetupStore.swift:147`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"baseURL: typedAddress.isEmpty ? rules.publishedBaseURL(trimmedProvider) : typedAddress,"`; `BoltrigTests/ProviderSetupTests/testNonNativeProviderSubmitsItsPublishedAddress` and `testIncompleteInputSaysWhatIsMissingWithoutSubmitting` | - |
| BT-REQ-1868 | The three provider routes turn a server-explained refusal into an outcome on 4xx and on 503 alike, and still throw anything without a sentence. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient+Onboarding.swift:45`](../../../ios/Boltrig/Networking/BoltrigClient+Onboarding.swift) `"private func aiKeyOutcome(path: String, method: String, body: Data?) async throws -> AIKeyOutcome {"`; `BoltrigTests/OnboardingTests/testClientTurnsServerSentencesIntoOutcomesAndThrowsTheRest` | - |
| BT-REQ-1869 | A server refusal reaches the person as the server's own sentence, capitalised and full-stopped and otherwise unchanged. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigError.swift:82`](../../../ios/Boltrig/Networking/BoltrigError.swift) `"let first = reason.prefix(1).uppercased()"`; `BoltrigTests/ProviderSetupTests/testServerReasonIsShownVerbatim` | - |
| BT-REQ-1870 | The bundled catalogue decodes off the main thread once per launch, inserts the self-hosted Ollama entry immediately before Ollama Cloud, requires a typed address for self-hosted and unpublished providers, and stores a model as `provider/model` unless the provider is custom. | IMPLEMENTED | [`ios/Boltrig/Models/ProviderCatalogue.swift:142`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"if id == \"ollama-cloud\" {"`; [`ios/Boltrig/Models/ProviderCatalogue.swift:184`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"func needsBaseURL(_ id: String) -> Bool {"`; `BoltrigTests/OnboardingTests/testBundledCatalogueLoadsOffMainWithSelfHostedOllamaBeforeOllamaCloud` and `testCatalogueRules` | - |
| BT-REQ-1871 | A catalogue that fails to decode falls back to `ProviderCatalogue.minimal`, so the provider step keeps its two rule-bearing entries. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/ProviderSetupStore.swift:63`](../../../ios/Boltrig/Session/ProviderSetupStore.swift) `"var rules: ProviderCatalogue { catalogue ?? .minimal }"`; `ProviderSetupTests` always injects a catalogue, so the fallback is never taken | - |
| BT-REQ-1872 | The five appearance keys are written together in one `PUT` and the read-replies flag in its own, and each restores the previous value with a notice when the write fails. | IMPLEMENTED | [`ios/Boltrig/Session/AccountSettingsStore.swift:50`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"appearance = previous"`; `BoltrigTests/AccountSettingsTests/testAppearanceWritesAllFiveKeysInOnePut`, `testAppearanceRollsBackWhenTheWriteFails`, `testReadRepliesRollsBackAndTellsNobodyWhenTheWriteFails` | - |
| BT-REQ-1873 | The approval posture is read-only on the phone: the client offers no write path and the screen tells the person to sign in on the web. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient+Account.swift:6`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift) `"The server refuses `PUT` on this route for the phone's key, so the phone only reads."`; `BoltrigTests/AccountSettingsTests/testPostureIsReadAndNeverWritten` asserts no PUT is recorded | - |
| BT-REQ-1874 | `GET /readyz` treats 503 as an answer and reads the report from its body, and nine probe ids are mapped to plain words. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient+Account.swift:48`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift) `"the body, so a 503 is an answer here and not a failure."`; [`ios/Boltrig/Models/AccountModels.swift:225`](../../../ios/Boltrig/Models/AccountModels.swift) `"static let labels: [String: String] = ["`; `BoltrigTests/AccountSettingsTests/testReadinessTolerates503AndMapsPlainLabels` | - |
| BT-REQ-1875 | Account deletion is refused twice, in the store and again in the client, and reaches the network in neither, while revoking the key this phone signs in with signs the phone out. | IMPLEMENTED | [`ios/Boltrig/Networking/BoltrigClient+Account.swift:72`](../../../ios/Boltrig/Networking/BoltrigClient+Account.swift) `"guard BoltrigEnvironment.accountDeletionAvailable else {"`; `BoltrigTests/AccountSettingsTests/testDeleteAccountNeverReachesTheNetworkWhileUnavailable` and `testTokensMarkThisPhoneAndRevokingItSignsOut` | - |
| BT-REQ-1876 | The preview workspace holds a nil client, so every screen shows its empty state and nothing reaches the network. | IMPLEMENTED | [`ios/Boltrig/Session/AccountSettingsStore.swift:189`](../../../ios/Boltrig/Session/AccountSettingsStore.swift) `"guard let client else {"`; `BoltrigTests/AccountSettingsTests/testPreviewStoreWritesNothingAndShowsEmptyStates` | - |
| BT-REQ-1877 | Every offline test runs against `StubURLProtocol`, and a request with no registered handler fails loudly rather than silently. | IMPLEMENTED | [`ios/BoltrigTests/StubURLProtocol.swift:64`](../../../ios/BoltrigTests/StubURLProtocol.swift) `"client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))"`; every test class in `ios/BoltrigTests/` except `LiveContractTests` | - |
| BT-REQ-1878 | The bundled provider catalogue is byte-identical to the web snapshot, and the only thing that catches a drift is a Swift test pinning its revision, because the sync script is wired into no target. | IMPLEMENTED | [`ios/scripts/sync-provider-catalogue.sh:21`](../../../ios/scripts/sync-provider-catalogue.sh) `"if cmp -s \"$source_file\" \"$target_file\"; then"`; `BoltrigTests/OnboardingTests/testBundledCatalogueLoadsOffMainWithSelfHostedOllamaBeforeOllamaCloud`; bounded: `rg -n 'sync-provider-catalogue' .` matches only the script and `ios/README.md`, 2026-08-24 | - |
| BT-REQ-1879 | The committed island page is byte-compared against a fresh build inside `worker-quality`, and a vitest suite asserts its size, self-containment, CSP hash and that it names no other companion. | IMPLEMENTED | [`Makefile:252`](../../../Makefile) `"familiar-island-check: ## Refuse a committed Familiar island page that apps/worker/src no longer builds"`; [`apps/worker/tests/familiarIsland.test.ts:402`](../../../apps/worker/tests/familiarIsland.test.ts) `"it(\"pins its inline script by the hash its CSP names\", () => {"`; that suite is the only automated gate anywhere that reads a file under `ios/` | - |
| BT-REQ-1880 | The phone app is built and tested only on the M4: nothing in CI builds it and the Makefile has no iOS target. | IMPLEMENTED-UNTESTED | [`ios/README.md:14`](../../../ios/README.md) `"Requires Xcode 26 on a Mac."`; bounded: `rg -n -i 'xcodebuild' .github/` and the same for `swift` return nothing, 2026-08-24. See RISK-1801 | - |
| BT-REQ-1881 | The test command deliberately leaves signing on, because the Keychain round trip needs a signed host app and skips itself without one. | IMPLEMENTED | [`ios/BoltrigTests/ClientAndParsingTests.swift:190`](../../../ios/BoltrigTests/ClientAndParsingTests.swift) `"} catch let error as Keychain.KeychainError where error.status == -34018 {"`; `BoltrigTests/ClientAndParsingTests/testKeychainRoundTrip` | - |
| BT-REQ-1882 | The archive exports with `app-store-connect` and automatic signing, the App Privacy answers must mirror `PrivacyInfo.xcprivacy`, and `ITSAppUsesNonExemptEncryption` is false while the app stays https-only. | IMPLEMENTED-UNTESTED | [`ios/ExportOptions.plist:8`](../../../ios/ExportOptions.plist) `"<string>app-store-connect</string>"`; [`ios/Boltrig/PrivacyInfo.xcprivacy:11`](../../../ios/Boltrig/PrivacyInfo.xcprivacy) `"<key>NSPrivacyCollectedDataTypes</key>"`; the runbook is a human procedure and no gate runs it or compares the manifest to the store record | - |
| BT-REQ-1883 | Adding a Swift file needs no project edit, and debug builds take launch arguments that open the preview workspace or first-run setup against a stub server answering five routes. | IMPLEMENTED-UNTESTED | [`ios/Boltrig.xcodeproj/project.pbxproj:36`](../../../ios/Boltrig.xcodeproj/project.pbxproj) `"isa = PBXFileSystemSynchronizedRootGroup;"`; [`ios/Boltrig/Support/SetupPreview.swift:16`](../../../ios/Boltrig/Support/SetupPreview.swift) `"switch (method, path) {"`; no test drives `SetupPreviewProtocol` and no gate reads the project file | - |
| BT-REQ-1884 | `Account.activeWorkspaceID` is decoded from the account route and read by no view. | DEAD | [`ios/Boltrig/Models/AuthModels.swift:121`](../../../ios/Boltrig/Models/AuthModels.swift) `"activeWorkspaceID: root[\"active_workspace_id\"] as? String,"`; bounded: `rg -n 'activeWorkspaceID' ios/` matches the model, two preview constructors and three test files, and no file under `ios/Boltrig/Views/`, 2026-08-24. See RISK-1814 and OQ-1807 | - |
| BT-REQ-1885 | `ConversationHistory.queuedMessageIDs` is decoded from `GET /v1/conversations/{id}` and read by nothing. | DEAD | [`ios/Boltrig/Models/ChatHistoryModels.swift:67`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"queuedMessageIDs: root[\"queued_message_ids\"] as? [String] ?? []"`; bounded: `rg -n 'queuedMessageIDs' ios/` matches only the declaration and that decode, 2026-08-24. See RISK-1814 | - |
| BT-REQ-1886 | `StoredMessage.hitlRequestID` is decoded from every stored message and read by nothing, so a history message never links back to its approval. | DEAD | [`ios/Boltrig/Models/ChatHistoryModels.swift:26`](../../../ios/Boltrig/Models/ChatHistoryModels.swift) `"hitlRequestID: object[\"hitl_request_id\"] as? String,"`; bounded: `rg -n 'hitlRequestID' ios/` matches only the declaration and that decode, 2026-08-24. See RISK-1814 | - |
| BT-REQ-1887 | `StoredMessage.attachments` and the whole `StoredAttachment` type are decoded and then dropped, because history messages are mapped to `ChatMessage`, which carries no attachments. | DEAD | [`ios/Boltrig/Session/ChatSession.swift:126`](../../../ios/Boltrig/Session/ChatSession.swift) `".map { ChatMessage(id: UUID(), role: $0.role == .user ? .user : .assistant, content: $0.content, createdAt: Date()) }"`; the only attachment view renders the outgoing tray, [`ios/Boltrig/Views/ChatView.swift:149`](../../../ios/Boltrig/Views/ChatView.swift) `"ForEach(chat.attachments, id: \\.name) { attachment in"`. See RISK-1814 | - |
| BT-REQ-1888 | The whole genotype-bound badge rendering path is unreachable: no call site sets `FamiliarBadgeView.identity` and no push sets `FamiliarIslandState.genotype`, so the four bodies, four markings and three accessories never draw and the seeded tilt is always zero. | DEAD | [`ios/Boltrig/Familiar/FamiliarBadgeView.swift:8`](../../../ios/Boltrig/Familiar/FamiliarBadgeView.swift) `"var identity: FamiliarVisualIdentity = .neutral"`; bounded: `rg -n 'FamiliarBadgeView\(' ios/` gives two call sites, both omitting `identity`, and `rg -n 'genotype' ios/Boltrig/` matches only the state field's declaration, 2026-08-24. `FamiliarBridgeTests/testGenotypeIdentity` constructs the identity directly, which is why the code compiles and is still unreachable. See RISK-1814 | - |
| BT-REQ-1889 | No test run exists for the pinned tree: the last recorded result predates two merged commits and counts 94 tests where 95 methods are present, so every IMPLEMENTED row above rests on a suite nobody has run at this commit. | UNCERTAIN | [`ios/README.md:32`](../../../ios/README.md) `"Last measured: 94 tests, 94 passed (2026-08-22)."`; [`ios/BoltrigTests/LiveContractTests.swift:29`](../../../ios/BoltrigTests/LiveContractTests.swift) `"func testSignInAdoptionReadsAndOneChatTurnAgainstTheInstance() async throws {"`. What would settle it: one `xcodebuild test` on the M4 with signing on, written back into `ios/README.md`. See OQ-1801 and RISK-1811 | - |
| BT-REQ-1890 | Sign-out revokes the phone's token best effort and clears the vault regardless, and the cookie session is closed best effort after the token is banked. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/SessionStore.swift:213`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)"`; [`ios/Boltrig/Session/SessionStore.swift:286`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await sessionClient.logout()"`; `BoltrigTests/SessionStoreTests/testSignOutRevokesThePhoneToken` covers the success path only. See RISK-1802 and RISK-1803 | - |
| BT-REQ-1891 | The phone mints its token with no requested scope, so the server stores the caller's whole allow set on a 90-day credential that lives in a pocket. | IMPLEMENTED-UNTESTED | [`boltrig/identity/tokens.py:69`](../../../boltrig/identity/tokens.py) `"requested = requested_scope if requested_scope else list(user_grants.allow)"`; the client body is built at [`ios/Boltrig/Networking/BoltrigClient.swift:70`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"[\"name\": name, \"ttl_days\": ttlDays]"`. See RISK-1804 | - |
| BT-REQ-1892 | The unreachable screen offers "Sign in again", which calls `signOut()` and destroys the stored credential, without saying so. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/App/BoltrigApp.swift:177`](../../../ios/Boltrig/App/BoltrigApp.swift) `"Button(\"Sign in again\") {"`; there is no UI test target. See RISK-1818 | - |
| BT-REQ-1893 | The island's navigation policy allows every `file:` URL, which is wider than the rule the comment above it states. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarIslandController.swift:159`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift) `"if navigationAction.request.url?.isFileURL == true {"`; no test in `ios/BoltrigTests/` exercises the navigation delegate. See RISK-1810 | - |
| BT-REQ-1894 | `"not authenticated"` sits in the session-reason set and matches nothing the server sends, and the comparison is exact and case-sensitive. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Networking/BoltrigClient.swift:291`](../../../ios/Boltrig/Networking/BoltrigClient.swift) `"static let sessionReasons: Set<String> = ["`; bounded: `rg -ni 'not authenticated' boltrig/` returns nothing, 2026-08-24. See RISK-1807 | - |
| BT-REQ-1895 | Moving the default instance off `https://dev.boltrig.ai` silently signs out every installed copy, because a stored session for another instance is discarded at launch and no migration path exists. | IMPLEMENTED | [`ios/Boltrig/Support/BoltrigEnvironment.swift:10`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift) `"static let hostedInstanceURL = URL(string: \"https://dev.boltrig.ai\")!"`; `BoltrigTests/SessionStoreTests/testRestoreForAnotherInstanceDiscardsTheToken` proves the discard. See RISK-1808 | - |
| BT-REQ-1896 | Three public links in the About section ship in the release build and point at pages the code itself records as not existing. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Views/SettingsView.swift:86`](../../../ios/Boltrig/Views/SettingsView.swift) `"Link(\"Privacy policy\", destination: BoltrigEnvironment.privacyPolicyURL)"`; no test and no gate resolves those URLs. See RISK-1809 | - |
| BT-REQ-1897 | The native-provider set with its alias table and Familiar's fallback voice ids are each a second copy of a source of truth that nothing keeps equal. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Models/ProviderCatalogue.swift:49`](../../../ios/Boltrig/Models/ProviderCatalogue.swift) `"static let bifrostSupported: Set<String> = ["`; [`ios/Boltrig/Speech/SpeechResolution.swift:12`](../../../ios/Boltrig/Speech/SpeechResolution.swift) `"static let familiarFallbackVoices: [String: String] = ["`; the web copy is pinned by `apps/worker/tests/providerCatalogue.test.ts`, the Swift copies by nothing. See RISK-1805 and RISK-1806 | - |
| BT-REQ-1898 | `AttachmentLimits.readableTypes` and `LinkedDevice.Root` are read from the server and rendered by no view, and the composer's footnote about readable files is a hard-coded sentence instead. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Session/ChatSession.swift:34`](../../../ios/Boltrig/Session/ChatSession.swift) `"static let attachmentsFootnote = \"Only text files are read. Photos and other files are kept with the message.\""`; [`ios/Boltrig/Models/LinkedDevice.swift:49`](../../../ios/Boltrig/Models/LinkedDevice.swift) `"let roots = (object[\"roots\"] as? [[String: Any]] ?? []).compactMap { root -> Root? in"`; bounded: `rg -n 'readableTypes' ios/` and `rg -n 'commandEnabled' ios/Boltrig/` match only declarations and decodes, 2026-08-24. See RISK-1815 | - |
| BT-REQ-1899 | `FamiliarVisualIdentity.validPalette` compiles its regular expression with `try!` on every call inside a per-frame badge, and `ios/` is absent from `.dockerignore`, so its 1.3 MB of Swift and bundled resources enter every image build context. | IMPLEMENTED-UNTESTED | [`ios/Boltrig/Familiar/FamiliarGenotype.swift:79`](../../../ios/Boltrig/Familiar/FamiliarGenotype.swift) `"let hex = try! NSRegularExpression(pattern: \"^#[0-9a-fA-F]{6}$\")"`; bounded: `grep -n 'ios' .dockerignore` returns nothing, 2026-08-24. No test measures either. See RISK-1813 and RISK-1812 | - |
