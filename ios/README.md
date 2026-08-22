# Boltrig for iPhone

Native SwiftUI client for Boltrig. It signs a person in to a Boltrig instance
(the hosted one by default), shows what needs them and what is working on Today,
streams a governed chat turn, and keeps a revocable per-phone credential in the Keychain.

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
`CODE_SIGNING_ALLOWED=NO`. Last measured: 21 tests, 21 passed (2026-08-22).

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

## Layout

```
Boltrig/App           BoltrigApp (root: restoring, signed out, signed in), ContentView (tabs)
Boltrig/Session       SessionStore (sign-in state machine), SessionVault (Keychain), AppStore (workspace data)
Boltrig/Networking    BoltrigClient (HTTP + SSE), ChatEvent (stream vocabulary), BoltrigError (plain copy)
Boltrig/Models        Account, sign-in outcomes, conversation and approval rows
Boltrig/Views         Today, Chat, Settings, Auth/ (sign-in, two-step, password change, enrolment, instance)
Boltrig/Support       environment + instance address, Keychain, theme, brand mark
Boltrig/Resources     asset catalog: app icon (from assets/brand/boltrig-app-icon.svg), accent colour
Boltrig/PrivacyInfo.xcprivacy   privacy manifest; keep in step with App Store Connect answers
BoltrigTests          XCTest: session ceremony, client decoding, SSE parsing, Keychain round trip
```

## What is not here yet

Native onboarding and companion stage, attachments, the full chat event rendering
(tool receipts, display objects, artifacts, subagents), reconnect to a live run,
push notifications, universal links, account deletion, crash reporting. The handover
document orders the rest of the work.
