# Production cutover runbook

This is the canonical Boltrig production cutover procedure. Historical host
notes and hand-built deployments are not instructions; use Git history when an
old incident or deployment record is needed.

## Current release posture (2026-08-13)

**HOLD production cutover until every precondition below has evidence.** The
repository is deliberately fail-closed:

- the **hosted browser agent** is test-only and rejects production and staging
  signals until the server-cell admission evidence in
  `CODEX-PRODUCTION-ADMISSION.md` is complete. This does not disable the
  desktop-local agent: a full desktop candidate bundles and verifies its own
  local Codex App Server and runs Bash on the user's computer;
- the `channels` profile is not admitted by the protected release path. Its
  first-party images are not in the signed release set and the secure network
  has no reviewed provider-egress path;
- release signing, notarisation, protected GitHub environments/rules, off-box
  recovery, alert delivery, and real-provider acceptance require external
  authority or infrastructure. Source code cannot manufacture that evidence.

A core service release with the hosted agent disabled, desktop omitted, and
channels disabled may be exercised in a production-like environment, but it is
not a usable full Boltrig agent product cutover.

### Protected release modes

The `release` GitHub environment must contain exactly one
`BOLTRIG_RELEASE_MODE` variable. Missing, mixed-case, whitespace-padded, or
otherwise decorated values fail before a draft is created:

- `full` is the complete product release. Browser Chat requires the hosted
  kernel-governed agent admission to be open. It also requires signed desktop candidates
  for Linux, macOS, and Windows, including updater signatures, Apple
  notarisation, Windows Authenticode evidence, and the exact bundled local Codex
  runtime receipt for each platform. The workflow must merge those three
  immutable platform fragments into `latest.json` before publishing the draft;
  only a stable full release may become the desktop updater's Latest release.
- `core` is an explicit server-only exception. It still requires all four
  digest-pinned images, vulnerability gates, signatures, CycloneDX SBOMs, SLSA
  provenance, recovery posture, the production doctor, and secure Compose
  validation. It skips the desktop jobs, refuses any desktop package or desktop
  evidence already attached to the draft, and records `mode=core`, desktop
  omission, disabled hosted-agent admission, omitted desktop-local-agent
  admission, and disabled channel admission in the immutable
  `release-metadata.json` asset. It does not claim that browser Chat works.

Do not use `core` as an implicit fallback when desktop signing fails. Changing a
draft between `full` and `core` is refused; choose the mode in the protected
environment before pushing the semantic tag. A core release is not evidence for
desktop, hosted-agent, local-agent, or channel acceptance.

## Cutover preconditions

All items are blocking. Record links or immutable artifact identifiers beside
each item in the change record.

1. **Protected source:** an immutable semantic tag points at the intended commit;
   canonical `ci / quality` and `security / Security gate` runs succeeded for
   that exact commit; required branch/tag rules and the `release` environment
   are active.
2. **Signed release set:** the protected release workflow produced the exact
   digest-pinned kernel, fleet, Worker UI, and backup images, with valid
   signatures, CycloneDX SBOM attestations, and SLSA provenance. The fleet
   digest covers both `fleet-worker` and `hatchet-worker`. For a full release,
   the same draft also contains three platform update fragments and one
   `latest.json` whose package URLs are bound to this tag; a core release must
   contain none of them and must not displace the latest full release.
3. **Desktop release:** updater signing, Apple notarisation, Windows
   Authenticode, and the protected HTTPS desktop API origin are configured; the
   packaged update path passed on supported platforms. Each installer contains
   the platform-specific official Codex 0.144.3 package staged by exact archive
   digest; the app rechecks the embedded executable digest and version before
   starting a local task.
4. **Exact deployment tree:** the host is checked out at the protected tag with
   no modified, staged, or deleted tracked files. Do not deploy a moving branch,
   copied working tree, or host-edited manifest/library/schema.
   On a self-hosted target, also complete the target-host preflight in
   `docs/DEPLOYMENT.md`: verify platform/image identity, uid-10001 volume
   ownership, distinct Fleet/Hatchet browser roots, Hatchet config continuity,
   and—whenever trusted Codex is requested—the named AppArmor profile plus the
   real sandbox engagement proof. The development image-relay procedure in that
   section is explicitly not release evidence.
5. **Production configuration:** `boltrig doctor --production` reports zero
   failures for the actual `.env` and `manifest.yaml`. Do not suppress a failed
   check. Hosted Codex requested by the manifest while server admission is closed is a failure
   except when the exact `core` release mode explicitly disables the hosted agent and
   `BOLTRIG_CODEX_TRUSTED` remains off. Invalid modes and that flag/mode conflict
   fail closed.
6. **Recovery:** a complete encrypted off-box recovery point exists for the
   Boltrig and Hatchet databases plus Hatchet config, Knowledge, libraries, and
   manifest. A disposable restore rehearsal proved authentication, audit/HITL,
   and one durable pause/resume. Record RPO, RTO, recovery timestamp, and
   Alembic head.
7. **Operations:** external monitoring receives `/readyz`, fleet-worker,
   Hatchet-worker, and backup-health failures and has a tested alert receiver.
   A protected, supply-chain-valid N-1 release and compatible recovery point are
   available for rollback.
8. **Capability acceptance:** every enabled external provider passed a real
   non-effectful canary. Leave the hosted browser agent and `channels` disabled
   until their separate admission gates are closed. Exercise desktop-local
   Bash/file approval postures independently on every supported package.

## Validate the candidate without changing production

From the exact protected-tag checkout, place the operator-owned `.env` and the
release's `boltrig-images.env` outside Git tracking. Install Cosign and a GitHub
CLI that supports `gh attestation verify`, then run:

The operator-owned `.env` must bind `BOLTRIG_RELEASE_MODE` to the exact mode in
the immutable release metadata; the value is propagated unchanged to every
server process that can admit a Codex-backed manifest.

```bash
make release-validate \
  RELEASE_ENV=.env \
  RELEASE_IMAGES_ENV=boltrig-images.env \
  RELEASE_TAG=vX.Y.Z
```

This admission gate does not start or change a production service. It requires a
clean tracked checkout, validates the secure Compose model, and verifies every
image signature, SBOM, provenance statement, tag, workflow identity, and source
commit before Docker may use a candidate digest. It then pulls the exact kernel
and fleet digests, assembles an unpushed ephemeral validation image from the
verified fleet bytes, executes the image-owned Browser CLI probe, and
runs production doctor inside that networkless, read-only context. `.env` is
streamed over stdin, never copied into the image; the validation image is removed
afterward, while pulled layers may remain cached. Missing tools, network access,
evidence, image executables, secrets, or authority fail closed. Do not replace
this with a host-side doctor or `docker compose config` alone: either would miss
the actual release-image tool context.

Validate the target manifest with the candidate kernel image as a separate
compatibility check:

```bash
docker run --rm --env-file .env \
  -v "$PWD/manifest.yaml:/m.yaml:ro" \
  "$(sed -n 's/^BOLTRIG_KERNEL_IMAGE=//p' boltrig-images.env)" \
  boltrig config-validate /m.yaml
```

Run the full recovery rehearsal before the maintenance window, not during it.
The following first verifies a downloaded encrypted recovery set without
decrypting, restoring, following symlinks, or modifying evidence; the second
exercises the dump/restore contract only in a newly created disposable
PostgreSQL container:

```bash
make recovery-verify \
  RECOVERY_MARKER=/secure/path/boltrig-<ts>.recovery.sha256
make recovery-rehearsal
```

When production uses custom logical database names, pass the exact configured
set as `RECOVERY_DATABASES=<application>,<hatchet>`; the verifier matches those
names to the names encoded in each encrypted dump artifact.

## Cut over

1. Announce the maintenance window and stop ingress/background writers.
2. Take and verify the final complete encrypted off-box recovery point.
3. Record `alembic current`, the protected tag, image digests, manifest digest,
   and recovery marker.
4. If migrations are required, rehearse them against the restored disposable
   copy first. Apply `alembic upgrade head` only with writers stopped.
5. Re-run `make release-validate` after the final configuration freeze.
6. Pull and start only the admitted digests:

   ```bash
   make release-up \
     RELEASE_ENV=.env \
     RELEASE_IMAGES_ENV=boltrig-images.env \
     RELEASE_TAG=vX.Y.Z
   ```

   `release-up` reruns validation, uses the release and secure overlays, pulls
   immutable images, and starts with `--no-build`. Do not add the `channels`
   profile and do not substitute `scripts/roll-release.sh` or hand-written
   Compose commands.

7. Keep ingress closed until all post-cutover checks pass.

## Post-cutover acceptance

Require and record:

- `/healthz` and `/readyz` succeed through the real edge;
- kernel, fleet-worker, Hatchet-worker, Worker UI, Postgres, Redis, Hatchet, and
  backup health are green with no restart loop;
- a clean-browser login, required 2FA, tenant/workspace scoping, and logout work;
- the database reports the packaged Alembic head;
- `/v1/audit/verify` reports an intact chain at the expected anchoring strength;
- a bounded ordinary task, exact HITL approval/deny flow, event reconnect, and
  durable pause/resume pass using only admitted runtimes;
- the external monitor receives a deliberate staging-only readiness failure and
  the backup completion marker is current;
- no secret, provider credential, prompt, or tool payload appears in logs.

Only then reopen ingress. Record who accepted the release and the exact evidence.

## Rollback

Rollback uses the protected N-1 image environment and the matching recovery
point. Run its `release-validate` first. If the schema is backward-compatible,
start the N-1 digests with `--no-build`. If it is not, stop writers and restore
the complete pre-cutover recovery set before starting N-1.

Never run `alembic downgrade` across an irreversible migration, never roll back
only application images across a schema change, and never restore Boltrig
without the matching Hatchet database/config. Preserve failed-release evidence
for investigation.

## Explicitly non-production paths

- `scripts/roll-release.sh` is retained only for legacy/dev investigation. It
  does not verify the current four-image signed release set and is not a
  production deployment command.
- Source builds, mutable tags, `git pull` on a live tree, hand-copied manifests,
  and local-only backups are not production releases.
- Removing an existing edge-authentication layer is a separate principal-gated
  change after the new authentication path has been proven behind it; it is not
  bundled into an application cutover.
