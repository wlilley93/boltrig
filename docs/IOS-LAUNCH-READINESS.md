# iPhone launch readiness: everything outside the code

Written 2026-08-22 against `main` at v0.4.42, for the question "what do I need to think about with
Boltrig that is not coding: error tracking, data and statistics, legal and privacy, App Store
requirements". Every "exists" below was read in the repository; every "missing" is a negative
search result, not a guess. Tags: **[BLOCKER]** stops an App Store submission, **[TESTFLIGHT]**
stops external TestFlight, **[SHOULD]** is expected of a shipped product, **[WILL]** is something
only Will can do (an account, a payment, a legal signature, a decision).

## 0. Where Boltrig stands today, in one table

| Area | Exists | Missing |
| --- | --- | --- |
| Error tracking | root logging config (`boltrig/api/logging_config.py`), liveness and readiness routes (`boltrig/kernel/health_routes.py`), doctor checks, a UI error boundary | any crash or error sink: no Sentry, no OpenTelemetry, no log shipping, no alerting, no structured logs |
| Statistics | tamper-evident audit ledger, `GET /v1/cost`, model telemetry reconstructed from audit rows (`boltrig/observability/model_telemetry.py`), budgets and spend (`boltrig/kernel/platform_routes/budgets.py`), console counts | product analytics of any kind, user or conversation counts over time, a metrics endpoint, uptime monitoring |
| Legal and privacy | encrypted secrets at rest (`boltrig/store/sealing.py`), 30-day conversation retention janitor (`boltrig/fleet/retention.py`), memory erasure route, a privacy-coverage API that is honest about what is unenforced (`boltrig/kernel/platform_routes/privacy_policy.py`), cookie banner on the marketing site | a privacy policy, terms, a subprocessor list, a DPA, account deletion, user data export, any GDPR text, a security contact, `security.txt`; the cookie banner links to `/privacy-policy`, which does not exist |
| App Store | a paid individual Apple Developer Program membership (Will, confirmed 2026-08-22), brand icon source (`assets/brand/boltrig-app-icon.svg`), macOS signing and notarisation in the desktop release workflow, the native app on this branch (`ios/`) | an App Store Connect record, demo credentials for review, push notifications, universal links (`/.well-known/apple-app-site-association` soft-404s the marketing home page), App Privacy answers, screenshots and metadata |
| Content rights | character constitutions and safety text in the prompts (`docs/characters/README.md`), voice licences tracked with a guard test (`THIRD_PARTY_NOTICES.md`) | clearance for the names Jarvis, Ultron and Colossus (Marvel and Forbin marks), consent for the cloned real voice (`docs/BACKUP-2026-08-14.md` records it as a real person's voice), a decision on the CC-BY-NC voices (`cosette`, `jean`) that cannot ship commercially |

## 1. Apple: accounts, records, distribution

1. **Apple Developer Program membership: in place.** Will confirmed on 2026-08-22 that he holds a
   paid individual membership (USD 99 a year), so TestFlight and App Store submission are open as
   soon as the App Store Connect record exists. Consequences of "individual": the seller name
   shown in the store is William Lilley, not Boltrig or a company; moving to an organisation later
   (D-U-N-S number, legal entity) is a separate account and an app transfer. The project carries
   team `5B68P8YVT8`, the team the M4's Xcode created the template project under; confirm it is the
   paid team in Xcode's Accounts settings before the first archive.
2. **[WILL] Bundle identifier is permanent.** The branch uses `ai.boltrig.app` (the Tauri desktop is
   `io.boltrig.worker`). Create the App Store Connect record with the same identifier; changing it
   after release is a new app.
3. **Distribution shape.** Boltrig is invite-only. Apple offers three shapes that fit:
   TestFlight only (up to 100 internal testers who are team members, 10,000 external testers by
   link, builds expire after 90 days), **unlisted** App Store distribution (full review, installable
   only by direct link, the right shape for an invite-only product), or public. Unlisted is
   requested through a form after the app is review-ready. Recommended order: internal TestFlight,
   external TestFlight with the first real invitees, then unlisted.
4. **[BLOCKER] Demo credentials for App Review.** Any login-gated app must give the reviewer a
   working account or a demo mode. Nothing in the repository provisions one. Needed: a dedicated
   review account on the hosted instance with onboarding already completed, a provider key
   already connected (review happens without your help), a conversation or two of sample history,
   and a short note explaining that Boltrig is invite-only and what to tap. The account must stay
   valid through the whole review window, and the backend must be up for it.
5. **Export compliance.** The app uses HTTPS only. `ITSAppUsesNonExemptEncryption` is set to false
   in `ios/Boltrig/Info.plist`, which removes the per-upload questionnaire. Keep it true only if
   you ever add your own cryptography.
6. **Age rating.** Apple's questionnaire (revised in 2025, with 13+, 16+ and 18+ tiers) asks about
   mature themes, unrestricted web access, user-generated content and, since 2025, whether the app
   contains AI-generated content that can be mature. Ultron is written to be "slightly cruel at
   the edges" (`apps/worker/src/bundles/ultron/character.json`) and the companions are an
   attachment surface; answer honestly and expect 13+ or higher. Decide whether the iPhone build
   ships all four companions or Familiar alone at first.
7. **[WILL] EU trader status.** Since February 2025, apps distributed in the EU must show the
   developer's trader status and contact details (Digital Services Act). If the seller is a
   business, you supply an address, phone and email in App Store Connect and they are shown
   publicly. If you do not intend to sell in the EU, restrict availability instead.
8. **Review notes that prevent the common rejections**: invite-only explanation, the demo account,
   that long-running work happens on the server and the app shows its state, that AI providers are
   configured by the account holder, that there are no purchases in the app.

## 2. App Store Review guidelines that bite this app specifically

| Guideline | What it asks | Boltrig today | Action |
| --- | --- | --- | --- |
| 4.2 minimum functionality | more than a repackaged website | the native app on this branch is native SwiftUI, not a WebView; the planned companion renderer in a small web view is fine | keep the shell native; do not ship a pure wrapper build |
| 2.1 completeness | no placeholders, no crashes, demo account | Settings rows now say "open on the web" instead of fake values; onboarding is web-only | finish onboarding natively or make the web handoff explicit in review notes; provide the demo account (1.4) |
| 5.1.1 data collection | privacy policy link in the app AND in App Store Connect; collect only what is needed | no policy exists; the app links to `https://boltrig.ai/privacy`, which does not exist yet **[BLOCKER]** | write and publish the policy (section 3) before the first external TestFlight |
| 5.1.1(v) account deletion | apps that support account creation must offer in-app account deletion | no deletion route exists; invite acceptance creates the account **[BLOCKER]** | add a server route and an in-app entry point (section 3.4) |
| 5.1.2 data use and sharing | disclose third parties who receive user data | user content goes to whichever AI provider the account connects (196 in the catalogue) | name the model in the policy: "your content is sent to the provider you connect" plus your own subprocessors |
| 1.2 user-generated content | filtering, reporting, blocking for UGC | no moderation, no report mechanism; content is AI-to-one-user, not user-to-user | likely out of scope (no sharing between users); say so in review notes; add a "report a problem with this reply" path if challenged |
| 5.2.1 intellectual property | no third-party names, characters or likenesses without rights | Jarvis, Ultron, Colossus are third-party marks; the bundles cite the films **[SHOULD, WILL]** | decide: licence, rename for the store build, or ship Familiar first |
| 4.8 Sign in with Apple | required only if another third-party social login is offered | first-party email and password only, OIDC is for enterprise | not triggered; do not add Google or similar sign-in without adding Apple |
| 3.1.1 in-app purchase | digital services sold in-app must use Apple's purchase | nothing is sold in the app; access is by invitation | not triggered; never link to a web purchase from the app (3.1.3) |
| 2.5.4 background | no background execution beyond the allowed modes | none used | push notifications are the honest way to surface approvals (section 6) |
| 5.1.1(ix) / 2.3 accuracy | metadata must describe the app | nothing written yet | description, keywords, screenshots per device size, support URL that works |

## 3. Legal and privacy

### 3.1 Documents that do not exist and must [BLOCKER for App Store, TESTFLIGHT for external]

1. **Privacy policy** at a public URL, linked from the app (Settings, already wired to
   `https://boltrig.ai/privacy`), from the marketing site footer and from the cookie banner
   (`site/src/components/common/Cookie/CookieBanner.tsx` links to `/privacy-policy`, a route that
   does not exist). Content it must cover, grounded in what the code actually does:
   - who the controller is (the legal entity behind Boltrig, contact address, and a privacy
     contact that is read: today `access@boltrig.io` is the only address and the domain has no
     mail routing, so nothing arrives);
   - what is collected: email, display name, role and workspace membership; conversations,
     attachments (up to 25 MiB, `boltrig/kernel/web_security.py`), approvals and the audit ledger;
     provider keys (sealed at rest, `boltrig/store/sealing.py`); sessions and personal access
     tokens; optional camera and microphone data for sensing and voice features;
   - where it goes: the AI provider the account holder connects (the catalogue at
     `apps/worker/src/components/onboarding/modelsDevCatalogue.json` lists 196), the hosting
     provider (Hetzner, Germany or Finland), Cloudflare (DNS, tunnel, TLS termination at their
     edge), the transactional email sender (MailerSend is referenced in tests), and any channel
     the person connects (Slack, WhatsApp, Telegram, email);
   - retention: conversations a person deletes are hard-purged after 30 days by the retention
     worker (`boltrig/fleet/retention.py`); everything else has no stated retention, which the
     policy must either state or you must implement;
   - rights: access, rectification, erasure, portability, objection, and how to exercise them
     (today erasure is per-conversation and per-memory only; export is an account summary, not an
     archive, per `boltrig/kernel/platform_routes/privacy_policy.py`);
   - AI disclosure: that replies are machine-generated, that the agent can take actions on
     connected accounts only after approval where the autonomy settings require it.
2. **Terms of service**: invite-only access, acceptable use, what the agent may do on your behalf
   and that you remain responsible for approvals, provider costs borne by the account holder,
   no warranty on generated output, liability cap, governing law (England and Wales if the entity
   is UK), termination and data return.
3. **Subprocessor list and DPA** for any organisation customer (the CV tenant already exists):
   a one-page list of the third parties above with locations and purposes, and a data processing
   agreement they can sign. UK GDPR Article 28 requires it for business customers.
4. **Security page and `security.txt`**: how to report a vulnerability, which address, what to
   expect. A reviewer following `/security` today gets the home page.

### 3.2 UK GDPR obligations for the controller [WILL][SHOULD]

- **ICO registration** (the data protection fee, tiered, roughly GBP 40 to 60 a year for a small
  organisation) is required for almost every UK organisation processing personal data.
- **Lawful basis** per purpose: contract for running the service, legitimate interests for
  security logging and product improvement, consent for anything optional (the cookie banner's
  analytics category currently gates nothing; if you add analytics it must gate them).
- **DPIA**: an AI agent that reads a person's email, calendar and documents and acts on them is
  the kind of "innovative technology" processing the ICO expects an impact assessment for. Write
  one before the first external customer; it also produces the content for the policy.
- **International transfers**: US providers are covered by the UK Extension to the EU-US Data
  Privacy Framework only if the specific provider is certified; otherwise the UK IDTA or the
  Addendum to the EU SCCs. The catalogue includes providers in jurisdictions with no adequacy
  at all; the policy must say the account holder chooses the provider and therefore the transfer.
- **Breach process**: 72 hours to notify the ICO for a reportable breach. Needs a documented
  owner, an inventory of where personal data lives (the backup document
  `docs/backup-restore.md` is a good start), and the error tracking in section 4 so you find out.
- **Retention schedule** written down, matching what the code does.
- **EU AI Act**, if any EU user: transparency obligations under Article 50 (people must be told
  they are interacting with an AI system; synthetic audio must be marked) apply from
  2 August 2026, which has passed. The companions' prompts instruct the model to avoid AI
  disclaimers in replies (`docs/characters/README.md` records the clean-room and the prompt
  rules); the disclosure therefore has to live in the UI and onboarding, once, clearly.

### 3.3 Content and rights decisions [WILL]

- **Character names: decided 2026-08-22, the iPhone ships Familiar only.** JARVIS and ULTRON
  are Marvel (Disney) marks; COLOSSUS is both a Marvel character and the Forbin Project AI. The
  phone bundle carries none of them and switches the account to Familiar on first sign-in
  (`docs/HANDOVER-2026-08-22-ios-app.md`, Part 3). The web keeps all four; record the store-build
  position in `THIRD_PARTY_NOTICES.md` when the store listing is written.
- **Voices**: `THIRD_PARTY_NOTICES.md` already bars the CC-BY-NC voices from a commercial build and
  a test guards it. The cloned real-person voice noted in `docs/BACKUP-2026-08-14.md` needs a
  written release from that person or it cannot ship in a product anyone pays for; Kyutai's
  usage policy, quoted in the notices, forbids cloning without lawful consent.
- **AI-generated content labelling**: one line in onboarding and one in the chat header is enough
  for Apple and for Article 50; it is not there yet.

### 3.4 Account deletion and data export, the engineering that legal needs [BLOCKER]

- A server route (for example `DELETE /v1/me` behind a fresh password or two-step check) that
  revokes sessions and tokens, removes memberships, closes conversations for the retention
  janitor, deletes memories, and leaves the audit ledger entries the hash chain needs (the ledger
  is keys-only by design, `boltrig/models/audit.py`, so it can stay). Organisation owners need a
  path too: an owner cannot delete an organisation with members from a phone, so the route should
  refuse with a plain reason and point at the web.
- An in-app entry point in Settings that explains what is removed and when, then calls it.
- A real data export (today `compliance_export` is hardcoded to an account summary).

## 4. Error tracking and observability (the "Sentry" question)

What exists: plain-text logging with a no-content rule (`boltrig/api/logging_config.py`, the
format carries timestamp, level and logger only), liveness and readiness, a PII classifier that
never mutates (`boltrig/kernel/pii.py`), an optional Langfuse metadata mirror. What does not:
any place where an exception from a real user's phone or from the kernel is collected, grouped,
alerted on and attached to a release.

Recommendation, in order:

1. **Zero-dependency baseline now**: turn on crash and energy reports in App Store Connect and
   look at Xcode's Organizer after every TestFlight build; adopt MetricKit later if you want them
   in your own store. TestFlight testers can send screenshots and notes from the app; read them.
2. **Sentry, both sides, before external TestFlight [SHOULD]**: the iOS SDK (sentry-cocoa via
   Swift Package Manager; it ships its own privacy manifest, which you must declare in the App
   Privacy answers as crash data) and the Python SDK in the kernel and fleet worker. Configure
   both with PII sending off, scrub email and message content (the server side must keep the
   no-content rule: never attach request bodies), set the release to the app version and the
   kernel tag so a crash maps to a build, sample performance traces low. Self-hosted Sentry is
   possible but is another system to run; hosted Sentry's free tier covers a launch. Add it to
   `THIRD_PARTY_NOTICES.md` and to the subprocessor list.
3. **Uptime and alerting**: an external monitor on the readiness route of each stack (hosted,
   dev, CV tenant) and on the marketing site, paging one phone. There is none today.
4. **Log shipping is optional** at this scale; structured JSON logs are the cheap step that makes
   grep and later shipping easy.

## 5. Data and statistics

What exists: the audit ledger is the source of truth and already yields calls, tokens, cost and
latency per model (`boltrig/observability/model_telemetry.py`), spend against budgets, pending
approvals and recent runs for the console. There is no count of users, active users, conversations
per day, approvals per day, or time to first reply, and no retention curve.

Recommendation: **derive, do not add a second store.** One read-only platform statistics route
over Postgres and the ledger (daily active accounts, conversations started, turns, approvals
answered and median time to answer, provider cost per account, crash-free rate from Sentry)
shown in the Operations surface, and exported weekly. This keeps the consolidation rule (one
source of truth) and avoids a third-party analytics SDK in the phone app, which would add a
tracking question to the privacy label and, if it ever used the advertising identifier, the App
Tracking Transparency prompt. App Store Connect gives installs, sessions and crashes for free,
for the share of users who opt in to sharing with developers (usually under half), so treat its
numbers as a sample.

If you still want product analytics later, the privacy-respecting choices that fit the phone are
TelemetryDeck (no personal data, designed for App Privacy answers) or a self-hosted PostHog; both
must be declared and both must honour the consent the cookie banner promises.

## 6. Operations a public client depends on [SHOULD]

- **A support mailbox that receives mail.** The three product domains have no MX records; the
  app's Support link and the privacy contact both need a working address before anyone outside
  the team installs.
- **Status page** and an incident process (who is paged, how users are told, what a postmortem
  looks like). `docs/PATH-TO-10.md` names incidents as future work; nothing exists.
- **Backups off the box**: `docs/BACKUP-2026-08-14.md` records that the voice clone files are a
  single copy and off-box backup is not done.
- **Compatibility with old app versions**: once the app is on phones you cannot recall, the
  `/v1` contract needs a deprecation rule and the app needs a minimum-version check (a readiness
  field or a header) so a build that can no longer talk to the server says so instead of failing
  oddly.
- **Rate limits on the authenticated read API**: limits exist on sign-in, channels and triggers,
  not on `/v1/me/*` reads; a misbehaving client or a stolen token should hit a ceiling.
- **Push notifications**: approvals are the one event that justifies interrupting a person. That
  needs an APNs key (a `.p8` from the developer account), a device-token registration route, a
  sender in the kernel, and the notification preferences that already exist on the server to
  grow a "phone" channel. Without it the phone only learns about an approval when opened.
- **Universal links**: invitation and reset emails carry web links; for them to open the app,
  `boltrig.ai` must serve a real `/.well-known/apple-app-site-association` JSON (today the path
  returns the marketing home page with HTTP 200) and the app must declare the associated domain.

## 7. The order to do it in

1. **Done 2026-08-22:** paid individual Developer Program membership confirmed. Open only if the
   seller should later become an organisation (new account plus app transfer).
2. **[WILL]** Set up a mailbox for support and privacy contact. Pick the seller and legal entity.
3. Write the privacy policy and terms (drafts can be produced from the inventory above; the
   lawyer reviews), publish them on `boltrig.ai` at the URLs the app already links, fix the
   cookie banner link, add `security.txt`.
4. Build account deletion and a real export (server route plus Settings entry).
5. Add Sentry to the kernel and the app; add an uptime monitor; write the breach and incident
   one-pager; register with the ICO; write the DPIA.
6. Done 2026-08-22 for the names (Familiar only on iPhone); the real-voice clone still needs a
   written release before any paid use; update `THIRD_PARTY_NOTICES.md` with the store position.
7. Create the App Store Connect record (`ai.boltrig.app`), internal TestFlight with your own
   phones, then external TestFlight with invitees, collecting crashes and feedback.
8. Provision the review account, write the review notes, answer App Privacy from the privacy
   manifest (`ios/Boltrig/PrivacyInfo.xcprivacy`) and the policy, submit as unlisted.

Items 3 to 6 are parallel with the native work in `docs/HANDOVER-2026-08-22-ios-app.md`; items 2
and 6 are the ones only Will can move.
