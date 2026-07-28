# [2026] VJS-CC-BOLTRIG-SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001 - opinion

First Instance, single judge, boltrig County. Case file: SUBMISSION-2026-07-28-201135.
Convening: CONVENING-county-2026-07-28-201143, case file
`sha256:8ad7d5e7a732776e9ddb2010b2d8dd79afbb9e56ecb1b766c4b7c198a7292847` (digest
recomputed at this seat and matching).

**No citation is minted**, for the reason recorded in the schema-validation ledger order
(2026-VJS-CC-BOLTRIG-SCHEMA-VALIDATION-LEDGER-001, read in full): `vjs next-citation`
refuses the canon COUNTY series at a subscriber seat ([2026] VJS-PC 19) and minting at
canon offers a number this repository's mirror already uses. The allocator gap is not
settled here.

**Implementation status: OPEN.**

---

## 1. Findings on the facts

Every file the pleading cites was opened and the cited lines checked; every external fact
was verified from this seat by the route named.

**F1 - CONFIRMED, with one precision.** CVE-2026-56852 is real: the Go vulnerability
database record GO-2026-5970 (fetched from api.osv.dev at this seat) carries it as an
alias, describes exactly the pleaded defect - a `norm.Iter` infinite loop on input
containing invalid UTF-8 bytes - and fixes it in `golang.org/x/text` 0.39.0. The package
is vendored inside the rclone binary copied at `deploy/backup.Dockerfile:37` from the
digest-pinned stage at `:16` (`rclone/rclone:1.74.4@sha256:c61954aa...`). The release
gate is as pleaded (`.github/workflows/release.yml:287-305`: severity HIGH,CRITICAL,
exit-code 1, reading `.trivyignore.yaml`). **Precision:** the gate runs with
`ignore-unfixed: true`, and it blocks anyway, because at the PACKAGE level a fix exists
(0.39.0) - trivy counts the finding as fixable even though no released ARTIFACT carries
the fix. "No fixed release" in F2 is true of rclone, not of x/text; the distinction is
what makes this a question at all. The HIGH severity is the scanner's classification: the
OSV/Go record carries no severity field, and nothing in this disposal turns on the letter
grade.

**F2 - CONFIRMED by direct measurement.** `gh release list --repo rclone/rclone` shows
v1.74.4 (2026-07-08) as Latest, and the go.mod fetched from the v1.74.4 tag pins
`golang.org/x/text v0.38.0` while master's go.mod pins `v0.40.0`. No released fix exists;
the next release will carry one.

**F3 - CONFIRMED, and strengthened against the pleading's own precedent section.**
`docs/dependency-policy.md` item 6 (`:63-70`) is as pleaded: accept only when no fixed
upstream release exists; record reachability, owner, expiry and a compensating control;
expired exceptions fail release review. The in-tree precedent exists
(`.trivyignore.yaml:32-44`, GHSA-hrxh-6v49-42gf, grpc vendored in the SAME binary, expiry
2026-10-23, same client-only argument). **Strengthened:** `scripts/python_audit.py:58-64`
shows the ledger was DESIGNED as "one ledger for every ecosystem so expiries are reviewed
in a single place" - non-Python entries are expiry-checked by the same fail-before-audit
machinery and only skipped for `--ignore-vuln` purposes. So the gRPC entry was not merely
claimed to be ledger-recorded; the mechanism was built expecting it to be.

**F4 - CONFIRMED.** `docs/security/accepted-advisories.json` holds exactly two entries
(PYSEC-2026-2447, GHSA-mh99-v99m-4gvg). The trivyignore gRPC statement's "Recorded in
docs/security/accepted-advisories.json" is false on the face of both files.

**F5 - CONFIRMED as to deployment posture; QUALIFIED as to the absolute.** The backup
service (`docker-compose.yml`, profile-gated `backup`) publishes no ports, mounts the
rclone config read-only from an operator-provisioned path, and runs only the fixed loop;
`scripts/backup.sh:97-98` invokes rclone strictly as a client (`rclone copy` of the
pg_dump artifact and its checksum to the operator-set `BACKUP_REMOTE`). **Qualification:**
"processes no untrusted text input" overstates it. rclone does process names and listings
returned BY the remote; the honest statement is that the only text reaching the
normalization path originates from operator-configured remotes and the sidecar's own
artifacts, so reaching the defect requires a compromised operator-provisioned remote - at
which point the attacker already holds the off-box backup channel. The acceptance must
carry the qualified statement, not the pleaded absolute.

**Correction to the Option A "Against" column:** "trivyignore entries lack the machine
enforcement" is only half true. Trivy honours `expired_at` in `.trivyignore.yaml`
(documented behaviour of the pinned trivy 0.72.0): past the date the ignore no longer
applies and the finding returns to the gate. The scan-level expiry therefore has teeth
already; what the trivyignore lacks is the ledger's fail-before-audit review and printed
accepted set - which engage only if the entry is mirrored there (F3-as-strengthened).

---

## 2. Precedent and authorities

**BINDING ON THE COST SIDE: 2026-VJS-CC-BOLTRIG-HITL-NOTIFICATION-ROUTING-001**, read in
full. Its D4 (discharge the cure on the live Classical Visas tenant, evidenced on the
tenant database) is outstanding, and the release this advisory blocks is the vehicle of
that court-ordered kernel cure (PR #169 merged). That is the weight in the scale against
Option C; it is not a reason to accept carelessly, and no part of this order touches that
order's directives.

**THE POLICY AS LAW OF THE FORUM: `docs/dependency-policy.md` item 6**, read with its
machine enforcement (`scripts/python_audit.py`, read in full). It answers the threshold
question directly: acceptance is lawful exactly when no fixed upstream release exists, on
a recorded reachability, owner, expiry and compensating control, with expiry that fails
review. F2 establishes the threshold; the directives below establish the record.

**NOT RELIED ON for any substantive point:** the remaining authorities listed by
`vjs route` for this issue (2026-VJS-CA-BOLTRIG-CODEX-APPROVAL-ROUTING-001,
2026-VJS-CC-BOLTRIG-AUDIT-DEPTH-001, -CHAT-ATTACHMENTS-001, -CHAT-AUTHORITY-001,
-CHAT-REGENERATE-001) speak to other questions and are not cited. No authority was relied
on that was not opened. The court notes for the record, per the standing warning from
another matter, that no authority styled "INV-8" exists in this repository and none is
cited.

---

## 3. Reasoning

The question is whether CVE-2026-56852 may be accepted in `.trivyignore.yaml`, and on
what conditions, or whether another route must be taken. All four pleaded options are
weighed.

**Option B - REFUSED.** Switch the backup image to rclone's `beta` tag. It takes the fix
today at the price of two controls worth more than the advisory closes on this record:
the digest-pinning discipline of `backup.Dockerfile:16` (a mutable tag is not a pin,
whatever is written beside it) and the released-artifact discipline generally - beta is
unreleased code on a production backup path, the one path whose entire purpose is
surviving the day everything else goes wrong. A gate defeated by moving the artefact off
its pin has not been satisfied; it has been vacated.

**Option C - REFUSED.** Hold v0.4.22 until rclone ships 1.74.5. This is the option the
gate's absolutism argues for, and it is refused on the verified record: the reachability
(F5-as-qualified) is genuinely absent as deployed, the cost is a court-ordered kernel
cure with a live-tenant D4 outstanding (HITL-NOTIFICATION-ROUTING-001), and the schedule
is upstream's, not ours. A gate that cannot be satisfied until a third party chooses to
ship is not a control on our supply chain; it is a lottery on theirs, held against a
tenant the court has already ordered cured. Where reachability is absent AND policy
provides a self-terminating mechanism, holding is not caution; it is the price of the
cure paid for no measured security gain.

**Option D - REFUSED.** Build rclone from source at a pinned master commit. It keeps a
pin and gains the fix, and trades away the thing the pin was buying: an official,
cosign-attested upstream artefact. The build toolchain joins the trusted set, attestation
regresses to self-build, and master-at-a-commit is unreleased code with a hash on it -
Option B's defect wearing Option A's costume. The provenance regression outruns the
advisory on the F5 record.

**Option A - ADOPTED, as modified, on the following ratio.** Accept the advisory in
`.trivyignore.yaml`, scoped to the vendored binary, with the full policy item 6 record,
AND mirror the acceptance into `docs/security/accepted-advisories.json` - repairing the
F4 drift in the same act by completing the record for the existing gRPC entry. Both
pleaded costs are real and both are answered. Suppression-by-statement is answered by the
record itself: owner, expiry, qualified reachability, drop condition, in two files, each
with machine teeth (trivy's `expired_at` at the scan; the ledger's fail-before-audit at
`make python-audit`). The F4 failure of record-keeping is answered not by declining the
acceptance but by repairing the record and binding the repair as a directive with a
checkable clause - the drift is an argument about HOW acceptances are recorded, not
about WHETHER this one is lawful.

> **THE RATIO.** An advisory may be accepted only where the fix cannot be taken - no
> released upstream artefact carries it - and only as a record, never as a silence:
> scoped to the operative path, owned, expiring, reachable-stated, and mirrored into the
> ledger whose machinery fails the review the day the statement goes stale. Where the fix
> CAN be taken it must be taken; the acceptance is self-terminating by expiry and
> self-cancelling by condition, so the gate loses nothing it was measuring. The
> alternative routes are refused because each destroys a control - the pin, the calendar,
> or the provenance - worth more, on the verified reachability record, than the advisory
> they close.

**Corollary 1, on checks.** A check of this acceptance must test the OPERATIVE artefact:
the trivy scan of the built backup image under the release gate's own invocation, and the
`python_audit.py` expiry machinery - not the presence of prose in a YAML file. An entry
that suppresses nothing, or a ledger row whose expiry cannot fail, is the
checkable-without-the-act defect class this court has corrected before.

**Corollary 2, on scope.** The acceptance is scoped to `usr/local/bin/rclone`. A global
ignore of CVE-2026-56852 would also silence the finding in any future image where x/text
IS reachable; the scoping is what keeps the statement true.

**Corollary 3, on precedence.** This acceptance is lawful because F2 is true on the day
it is made. The day a released rclone carries x/text >= 0.39.0 the ratio inverts: a fix
exists, and policy item 6 commands that it be taken. The drop condition is not a courtesy
in the statement; it is part of the holding.

---

## 4. Disposition

Option A **adopted as modified**: the acceptance is entered in `.trivyignore.yaml`
(scoped, owned, expiring 2026-10-23, qualified reachability, drop condition) AND mirrored
with the existing gRPC entry into `docs/security/accepted-advisories.json`, the F4 drift
being repaired by completing the record rather than editing prose. Options B, C and D
**refused**, each on stated grounds.

**Reserved, not decided.** The general question of whether `.trivyignore.yaml` statements
should be schema-validated against the ledger (so a claim like the gRPC entry's cannot
drift again) is not before the court and is not ordered; the repair here is the record,
not the tooling.

---

## 5. Limits, recorded rather than ordered

**L1.** The acceptance buys the release gate, nothing else. It does not touch the vendored
x/text, and if the backup service's posture changes - a port published, a remote pointed
at infrastructure the operator does not control, rclone invoked on user-supplied paths -
the F5 statement becomes false and the acceptance must be re-pleaded, not edited.

**L2.** The HIGH classification is the scanner's (F1). The disposal rests on reachability
and the absence of a fixed release, and would be the same at MODERATE.

**L3.** The expiry 2026-10-23 matches the gRPC entry's horizon so both acceptances on the
same binary come due together, in the same review, against the same upstream release.

---

## 6. Obiter

**O1.** The F4 drift is the second record-keeping failure this term to be discovered by a
case file rather than by the mechanism the record claimed. The ledger's design comment
(python_audit.py:58-61) already knew the answer - one ledger, every ecosystem, expiries
reviewed in a single place. The defect was never design; it was that nothing made the
claim in the trivyignore statement CHECKABLE. D2 and D3 are drafted against exactly that.

**O2.** This is the second advisory accepted against the same pinned rclone binary on the
same client-only argument in one quarter. The pattern is sound and the expiry teeth are
real, but two acceptances on one artefact is a signal about the artefact: the day the
backup path can take rclone from a source whose release cadence matches its dependency
hygiene, the question stops recurring. No directive; the observation stands for the next
case file.
