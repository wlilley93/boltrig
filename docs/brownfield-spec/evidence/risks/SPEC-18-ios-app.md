# Risks harvested from SPEC-18-ios-app.md

RISK-1801: **Nothing automated verifies this area.** No CI job, no Makefile target and no
invariant reaches the Swift tree; the only gate is a person running `xcodebuild test` on the
one Mac. Bounded: `rg -n -i 'xcodebuild|ios|swift' .github/` returns nothing;
`rg -n -i 'ios|iphone|swift' Makefile` matches only the two `familiar-island` targets, whose
work is in `apps/worker`; `tests/invariants.yaml` binds pytest node ids only
([`tests/invariants.yaml:3`](../../../tests/invariants.yaml) `"a one-line meaning plus the pytest node ids"`).

---

RISK-1802: **Sign-out revokes the token best-effort and clears the vault regardless.** If the
revoke call fails for any reason, including no network, the phone forgets a credential that
is still live on the server for up to 90 days, and the person has no signal that it was not
revoked ([`ios/Boltrig/Session/SessionStore.swift:213`](../../../ios/Boltrig/Session/SessionStore.swift)
`"try? await tokenClient(stored.secret).revokeAccessToken(id: stored.tokenID)"`).
`SessionStoreTests/testSignOutRevokesThePhoneToken` covers only the success path.

---

RISK-1803: **The cookie session is closed best-effort too.** A failed logout leaves a live
web session on the server after the phone has already banked its token
([`:286`](../../../ios/Boltrig/Session/SessionStore.swift) `"try? await sessionClient.logout()"`).

---

RISK-1804: **The phone's key carries the owner's entire grant set.** The client sends only
`{name, ttl_days}` ([`ios/Boltrig/Networking/BoltrigClient.swift:70`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
`"[\"name\": name, \"ttl_days\": ttlDays]"`), and with no `scope` the server stores the
caller's own allow set ([`boltrig/identity/tokens.py:69`](../../../boltrig/identity/tokens.py)
`"requested = requested_scope if requested_scope else list(user_grants.allow)"`). A phone in
a pocket therefore holds an unscoped credential for a superadmin, for 90 days, where the app
itself calls at most about thirty routes.

---

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

---

RISK-1806: **Familiar's voice ids are a second, ungated copy of the character bundle.**
`SpeechResolution.familiarFallbackVoices` hard-codes `fish: c8f64deb39914cfca7f47ccfc3bca82f`
([`ios/Boltrig/Speech/SpeechResolution.swift:14`](../../../ios/Boltrig/Speech/SpeechResolution.swift)
`"\"fish\": \"c8f64deb39914cfca7f47ccfc3bca82f\","`), which is a copy of
[`apps/worker/src/bundles/familiar/character.json:63`](../../../apps/worker/src/bundles/familiar/character.json)
`"\"fish\": \"c8f64deb39914cfca7f47ccfc3bca82f\","`. Nothing keeps them equal; a bundle change
makes the phone request a voice that no longer exists, and the failure is silent by design
(9, speech row).

---

RISK-1807: **`"not authenticated"` in `sessionReasons` matches nothing the server sends.**
Bounded: `rg -ni 'not authenticated' boltrig/`, 2026-08-24, pinned tree, returns nothing, and
no `HTTPBearer` is used anywhere in `boltrig/`. A 401 carrying that reason would be
classified `.rejected` rather than `.unauthenticated`
([`ios/Boltrig/Networking/BoltrigClient.swift:291`](../../../ios/Boltrig/Networking/BoltrigClient.swift)
`"static let sessionReasons: Set<String> = ["`). The comparison is also exact and
case-sensitive, so a reason that differs only in case would be misclassified.

---

RISK-1808: **The default instance is a preview host, and changing it signs everyone out.**
`hostedInstanceURL` is `https://dev.boltrig.ai`
([`ios/Boltrig/Support/BoltrigEnvironment.swift:10`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"URL(string: \"https://dev.boltrig.ai\")!"`). Because `restore()` discards a stored session
whose instance does not match ([`ios/Boltrig/Session/SessionStore.swift:75`](../../../ios/Boltrig/Session/SessionStore.swift)
`"guard stored.instanceURL == instanceURL else {"`), the eventual move to a production host is
a silent forced sign-out of every installed copy, with no migration path in the code.

---

RISK-1809: **Three public links in Settings point at pages that do not exist**, by the code's
own admission ([`ios/Boltrig/Support/BoltrigEnvironment.swift:12`](../../../ios/Boltrig/Support/BoltrigEnvironment.swift)
`"These pages do not exist on boltrig.ai yet"`). They ship in the release build and are
reachable from the About section today
([`ios/Boltrig/Views/SettingsView.swift:86`](../../../ios/Boltrig/Views/SettingsView.swift)
`"Link(\"Privacy policy\", destination: BoltrigEnvironment.privacyPolicyURL)"`).

---

RISK-1810: **The island's navigation policy allows every `file:` URL, not only the bundled
page.** ([`ios/Boltrig/Familiar/FamiliarIslandController.swift:159`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"if navigationAction.request.url?.isFileURL == true {"`). The comment above it claims a
narrower rule ([`:158`](../../../ios/Boltrig/Familiar/FamiliarIslandController.swift)
`"Only the bundled page may load"`). The page's own CSP is `default-src 'none'` with no
`connect-src`, so nothing in it can currently attempt a navigation, but the guard does not
say what its comment says.

---

RISK-1811: **The recorded test count is stale by one.** `ios/README.md` says 94 tests
([`ios/README.md:32`](../../../ios/README.md) `"Last measured: 94 tests, 94 passed (2026-08-22)"`),
the tree contains 95 test methods, and the handover already says 95
([`docs/HANDOVER-2026-08-22-ios-app.md:694`](../../../docs/HANDOVER-2026-08-22-ios-app.md)
`"95 tests, of which one skips itself without a live credential"`). The 95th,
`LiveContractTests`, landed in `16356a79` after the README was measured. A count that is one
low is exactly the kind of number a later reader trusts.

---

RISK-1812: **`ios/` is not in `.dockerignore`.** No image copies it (3), but every kernel,
fleet and worker build sends 1.3 MB of Swift, a 404 KB JSON snapshot, a 164 KB HTML page and
a 50 KB PNG into the daemon's build context on a box where build memory has been a problem.
Bounded: `grep -n 'ios' .dockerignore` returns nothing, 2026-08-24, pinned tree.

---

RISK-1813: **`FamiliarVisualIdentity.validPalette` uses `try!` on a regular expression.**
([`ios/Boltrig/Familiar/FamiliarGenotype.swift:79`](../../../ios/Boltrig/Familiar/FamiliarGenotype.swift)
`"let hex = try! NSRegularExpression(pattern:"`). The pattern is a constant so it cannot
throw today, but it is also recompiled on every call, inside a badge that draws per frame.

---

RISK-1814: **Four decoded fields and one whole rendering path are unreachable from any app
call site**, so a reader can believe the app does more than it does. See
BT-REQ-1884 to BT-REQ-1888 in the requirements table. None is a defect on its own; together they are a
map that does not match the territory.

---

RISK-1815: **`AttachmentLimits.readableTypes` is read from the server and never used.** The
composer's footnote is a hard-coded sentence
([`ios/Boltrig/Session/ChatSession.swift:34`](../../../ios/Boltrig/Session/ChatSession.swift)
`"Only text files are read. Photos and other files are kept with the message."`), so a
deployment that widens `model_readable_media_types` will have the phone tell people something
untrue. Bounded: `rg -n 'readableTypes' ios/`, 2026-08-24, pinned tree, matches only the
declaration and the decode.

---

RISK-1816: **`ReplySpeaker` accepts up to 12,000,000 base64 characters, about 9 MB of audio,
decoded whole into memory** on a phone ([`ios/Boltrig/Speech/ReplySpeaker.swift:24`](../../../ios/Boltrig/Speech/ReplySpeaker.swift)
`"static let maxAudioBase64 = 12_000_000"`). The check is after the whole body has already
been read by `session.data(for:)`, so the bound limits what is decoded, not what is received.

---

RISK-1817: **Attachment bytes travel base64 inside the chat JSON body**, so a 1 MiB total
becomes roughly 1.4 MB of JSON built entirely in memory
([`ios/Boltrig/Models/ChatHistoryModels.swift:79`](../../../ios/Boltrig/Models/ChatHistoryModels.swift)
`"[\"name\": name, \"media_type\": mediaType, \"data\": data.base64EncodedString()]"`).

---

RISK-1818: **The unreachable screen offers "Sign in again", which calls `signOut()`**, so a
person who taps it while genuinely offline destroys their stored credential and must type a
password ([`ios/Boltrig/App/BoltrigApp.swift:177`](../../../ios/Boltrig/App/BoltrigApp.swift)
`"Button(\"Sign in again\") {"`). The label does not say that.

---
