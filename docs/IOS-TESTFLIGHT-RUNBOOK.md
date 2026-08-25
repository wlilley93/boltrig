# Boltrig for iPhone: TestFlight runbook

Prepared 2026-08-22 against `ios/` on `feat/ios-app` (94 tests passing). Everything here is
ready except the steps that need Will's Apple login, which are marked **[WILL]**. The audit of
what is missing outside the code is `docs/IOS-LAUNCH-READINESS.md`; this file is the sequence
of steps for a build.

Facts the steps rely on (all read from `ios/Boltrig.xcodeproj/project.pbxproj` and
`ios/Boltrig/Info.plist`): scheme `Boltrig`, bundle id `ai.boltrig.app`, team `5B68P8YVT8`,
automatic signing, `MARKETING_VERSION` 1.0, `CURRENT_PROJECT_VERSION` 1, iOS 17.0, iPhone only,
portrait, category Productivity, `ITSAppUsesNonExemptEncryption = NO` (https only, so no
export-compliance questionnaire per upload).

## 1. The record in App Store Connect [WILL]

1. App Store Connect, Apps, New App: platform iOS, name "Boltrig", primary language English
   (UK), bundle id `ai.boltrig.app` (register it first under Certificates, Identifiers and
   Profiles if the list does not offer it; capabilities: none beyond the defaults), SKU
   `boltrig-ios`, access Full.
2. Under the app's TestFlight tab, create an internal group (you, any teammate with an App
   Store Connect role). External groups need the first build to pass beta review and the legal
   pages to exist (`docs/IOS-LAUNCH-READINESS.md` section 3.1).
3. Under App Information, set the category Productivity and the content rights answer
   ("does not contain, show or access third-party content" is wrong once the model's replies
   count; answer that it does, and that you have the rights: the replies come from the provider
   the person connects).

## 2. Archive and export

Build number must be unique per upload. Bump `CURRENT_PROJECT_VERSION` in the project (or pass
it on the command line as below) before every archive.

From Xcode (simplest): open `ios/Boltrig.xcodeproj`, destination "Any iOS Device (arm64)",
Product, Archive; in the Organizer press Distribute App, choose App Store Connect, Upload,
accept automatic signing. Xcode creates the distribution certificate and profile on first use
when you are signed in under Settings, Accounts. **[WILL]** for the sign-in and the upload.

From a terminal on the M4 (the same, scripted; Xcode must be signed in to the Apple ID once
for `-allowProvisioningUpdates` to mint the distribution profile):

```bash
cd ios
BUILD=$(date +%Y%m%d%H%M)          # any strictly increasing integer; uniqueness is all Apple needs
xcodebuild -project Boltrig.xcodeproj -scheme Boltrig \
  -destination 'generic/platform=iOS' \
  -archivePath build/Boltrig.xcarchive \
  CURRENT_PROJECT_VERSION="$BUILD" \
  -allowProvisioningUpdates archive

xcodebuild -exportArchive \
  -archivePath build/Boltrig.xcarchive \
  -exportOptionsPlist ExportOptions.plist \
  -exportPath build/export \
  -allowProvisioningUpdates
# build/export/Boltrig.ipa is the artefact
```

Upload **[WILL]**: either drop `build/export/Boltrig.ipa` on the Transporter app (Mac App
Store, signed in with the Apple ID), or change `destination` in `ios/ExportOptions.plist` to
`upload` and re-run the export step, which then uploads directly; that path needs an App Store
Connect API key (`-authenticationKeyPath`, `-authenticationKeyID`,
`-authenticationKeyIssuerID`) or the signed-in Xcode.

Processing takes 5 to 30 minutes; the build then appears under TestFlight. Add it to the
internal group; the TestFlight app on the phone installs it. The first build for an external
group is held for beta review (usually under a day).

## 3. App Privacy answers

These mirror `ios/Boltrig/PrivacyInfo.xcprivacy`, which the build carries; the two must agree.
All data is "linked to the user", none is "used for tracking", and the only purpose is
App Functionality. Nothing is collected for analytics, advertising or product personalisation,
because no analytics or crash sink exists yet (revisit when error tracking is added; a crash
reporter adds Diagnostics, Crash Data).

| Apple's data type | Collected? | Why the app sends it |
| --- | --- | --- |
| Contact Info, Email Address | yes, linked | sign-in and the account record |
| Contact Info, Name | yes, linked | the display name the person gives in setup |
| Identifiers, User ID | yes, linked | the account id the server assigns |
| User Content, Other User Content | yes, linked | chat messages and the files attached to them |
| User Content, Photos or Videos | yes, linked | a photo the person chooses to attach to a message; the app never reads the library |
| User Content, Audio Data | no | the app plays replies; it does not record |
| Location, Contacts, Health, Financial, Browsing, Search, Purchases | no | never requested |
| Usage Data, Diagnostics | no | no analytics, no crash reporting (yet) |

"Does this app use data to track users?" No. "Third parties": user content goes to the AI
provider the person connects in setup (named in the privacy policy, which must exist first:
section 3.1 of the readiness document).

## 4. Review notes (draft, paste into the App Review Information field)

> Boltrig is an invite-only assistant for one person's own account. The app signs in to a
> Boltrig instance (by default our hosted one) with an email and password that an
> administrator issues; there is no public sign-up. Sign in with the review account below.
>
> Review account: **[to be provisioned: a hosted account with a connected provider, no
> two-step verification, on the hosted instance]**. Password: **[…]**.
>
> After sign-in the app runs a short setup (your name, connect your AI, an optional image
> model). The review account already has a provider connected, so setup passes through in a
> few presses. Then: Today (approvals and working chats), Chat (ask Familiar anything; replies
> come from the connected AI provider and are labelled as generated), Settings.
>
> Replies are generated by the AI provider the person connected; the app says so on the
> Ready screen and does not present generated text as human. There is no user-to-user
> content and no sharing between accounts. The companion "Familiar" is our own character.
>
> "Read out replies" in Settings, Look, speaks finished replies through the server's voice
> service; it is off by default. Photos and files a person attaches travel to their own
> instance with the message. The app does not track, advertise, or collect analytics.
>
> Account deletion: **[blocker until the server route exists; until then the Delete account
> screen is disabled and points at support]**. Privacy policy: https://boltrig.ai/privacy.
> Terms: https://boltrig.ai/terms. Support: **[mailbox to be created]**.

## 5. Age rating and the remaining metadata [WILL]

Answer Apple's questionnaire from what the app does: no violence, sexual content, gambling,
contests or unrestricted web access in the app itself; generated AI content is present and
comes from the provider the person connects; no user-to-user interaction. Let the tool compute
the rating from honest answers rather than aiming for a tier.

Metadata still to write: the description (plain sentences about what it does, no technology
names), keywords, the support URL (must answer; today nothing does), the marketing URL
(`https://boltrig.ai`), screenshots for the current required iPhone size (App Store Connect
states which at upload time; capture on the simulator with `xcrun simctl io booted screenshot`
from the preview workspace, or on the phone), and the privacy policy URL, which must resolve
before the first external TestFlight.

## 6. What blocks each stage, precisely

- Internal TestFlight (your phone): only the App Store Connect record and the upload. Nothing
  else.
- External TestFlight (invitees): the privacy policy at the linked URL (Apple asks for it on
  the first external build), a support URL that answers, and beta review.
- Store submission (unlisted): everything in `docs/IOS-LAUNCH-READINESS.md` marked Blocker:
  the review account, in-app account deletion with its server route, terms, the mailbox.
