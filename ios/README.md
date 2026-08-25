# Boltrig for iPhone

Native SwiftUI client for Boltrig, Familiar only. It signs a person in to a Boltrig
instance (the hosted one by default), runs first-run setup, shows what needs them and what is
working on Today, streams a governed chat turn with Familiar's presence, reads finished
replies aloud in her voice, and keeps a revocable per-phone credential in the Keychain.

State of play and the plan live in `docs/HANDOVER-2026-08-22-ios-app.md`; the non-code
work needed before anyone outside the team installs it (Apple accounts, legal pages,
account deletion, error tracking) lives in `docs/IOS-LAUNCH-READINESS.md`.

## Open, build, test

Requires Xcode 26 on a Mac. Everything under `ios/Boltrig` and `ios/BoltrigTests` is
picked up automatically (synchronized folders), so adding a file needs no project edit.

```bash
cd ios
open Boltrig.xcodeproj                       # then pick an iPhone simulator and press Run

# the same from a terminal, no signing needed for the simulator
xcodebuild -project Boltrig.xcodeproj -scheme Boltrig \
  -destination 'platform=iOS Simulator,name=iPhone 17' \
  CODE_SIGNING_ALLOWED=NO build

xcodebuild -project Boltrig.xcodeproj -scheme Boltrig \
  -destination 'platform=iOS Simulator,name=iPhone 17' test
```

Run the tests with signing left on (the simulator signs ad hoc, no team needed): the
Keychain round-trip test needs a signed host app and skips itself under
`CODE_SIGNING_ALLOWED=NO`. Last measured: 94 tests, 94 passed (2026-08-22).

Running on a real iPhone needs a signing team selected under Signing and Capabilities.
The project carries the team that created it; pick your own if Xcode asks.

## How it signs in

1. Email and password go to `POST /v1/auth/login` on a short-lived cookie session.
2. The server may ask for a two-step code, a new password, or two-step setup; each has a screen.
3. The app then mints a personal access token for this phone (`POST /v1/me/tokens`,
   90 days), stores only that token in the Keychain, and closes the cookie session.
4. Every later request carries the token. Sign out revokes it on the server and forgets it.

The token shows up in the web app's token list under a name like
"iPhone app, signed in 2026-08-22", so it can be revoked from anywhere.

## Which Boltrig it talks to

`BoltrigEnvironment.hostedInstanceURL` (`Boltrig/Support/BoltrigEnvironment.swift`) is the
default, `https://dev.boltrig.ai` today. The sign-in screen has a "Connected to" link that
lets a person point the app at another https instance, for example a self-hosted box.
Only https is accepted. Changing instance signs out, because a token belongs to one instance.

## Familiar's presence

The presence is the worker's own shader, built into one self-contained page and bundled at
`Boltrig/Resources/FamiliarIsland/familiar-island.html` with a manifest beside it. Rebuild it
from the repository root with `make familiar-island` after a renderer change;
`make familiar-island-check` (part of `worker-quality`) fails when the bundled page is stale.
For simulator captures, debug builds take launch arguments: `-boltrigPreview -boltrigTab
today|chat|settings -boltrigEmptyChat` for the signed-in screens, and `-boltrigOnboarding
-boltrigStep name|provider|vision|ready` for first-run setup against a stub server. A live run
against a real instance is `BoltrigTests/LiveContractTests` with
`TEST_RUNNER_BOLTRIG_LIVE_EMAIL` and `TEST_RUNNER_BOLTRIG_LIVE_PASSWORD` set (it skips itself
otherwise; use a throwaway account, it switches the companion to Familiar and sends one turn).

The page reports `ready`, `fallback` and frame rates to the unified log under the
`ai.boltrig.app` subsystem (`log show --info --predicate 'subsystem == "ai.boltrig.app"'`).
When the page is missing or reports no WebGL, the SwiftUI badge shows instead.

The provider catalogue for first-run setup is the web's snapshot, bundled verbatim at
`Boltrig/Resources/ProviderCatalogue.json`; `scripts/sync-provider-catalogue.sh` copies it and
`--check` fails when the two differ (a test pins the revision).

## Layout

```
Boltrig/App           BoltrigApp (root: restoring, signed out, setup, signed in), ContentView (tabs, theme)
Boltrig/Session       SessionStore (sign-in, Familiar adoption), SessionVault (Keychain), AppStore (workspace),
                      ChatSession (history, live turn, follow, questions, attachments), OnboardingStore,
                      ProviderSetupStore (one-press provider rule), AccountSettingsStore (settings writes)
Boltrig/Networking    BoltrigClient (+Chat, +Devices, +Platform, +Onboarding, +Account), SSEByteReader,
                      ChatEvent (stream vocabulary), BoltrigError (plain copy)
Boltrig/Models        Account and appearance, CompanionPresence, chat history and attachments, linked devices,
                      provider catalogue and keys, account settings readings
Boltrig/Familiar      island bridge and controller (one web view, claim per surface, phenotype poll),
                      presence view, badge and genotype
Boltrig/Speech        SpeechResolution (who speaks, which voice), ReplySpeaker (invoke, play, meter)
Boltrig/Views         Today, Chat (+Chat/ pieces), Settings (+Settings/ screens), Onboarding/, Auth/
Boltrig/Support       environment + instance address, Keychain, theme, brand mark, AttachmentImporter
Boltrig/Resources     asset catalog, FamiliarIsland/ (page + manifest), ProviderCatalogue.json
Boltrig/PrivacyInfo.xcprivacy   privacy manifest; keep in step with App Store Connect answers
BoltrigTests          XCTest against an in-memory URLProtocol stub: session ceremony, adoption, client
                      decoding, SSE framing, chat session, island bridge, phenotype poll, speech,
                      attachments, linked devices, onboarding and provider setup, account settings
scripts/              sync-provider-catalogue.sh
```

## What is not here yet

Push notifications, universal links, account deletion (waits on a server route; the screen is
behind a flag), crash reporting, live voice calls, a Metal port of the shader. The handover
document orders the rest of the work and records the measured presence budgets.
