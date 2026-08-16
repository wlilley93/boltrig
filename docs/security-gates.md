# Security gates

Boltrig has two stable CI aggregator checks, and as of 2026-07-25 they ARE
required on `main` ([2026] VJS-CC-BOLTRIG-BRANCH-PROTECTION-001, Order 2). The
protection contexts are the check-run names `quality` and `Security gate` - NOT
the `ci / quality` form this document previously recited, which no check run
publishes; requiring a context nothing reports would block every merge forever.

State the control's ACTUAL scope, because the previous sentence ("Both must be
successful before merge") was untrue while the protection endpoint returned 404,
and later overstated it:

- Required on pull requests, and for every NON-ADMIN actor - including
  `release.yml`'s `GITHUB_TOKEN` and Dependabot.
- `enforce_admins` is FALSE, so the sole admin retains a bypass. This is
  deliberate and was refused as a strong-form order for now: `security.yml` sets
  `cancel-in-progress`, so at the current push cadence a run on `main` is often
  cancelled rather than failed, and admin enforcement would produce a gate with
  no lawful path through it.
- `strict` is FALSE, so a branch need not be rebased onto the tip to merge.

Conditions for tightening to `enforce_admins: true` are recorded in that order:
stop cancelling in-progress runs on `main`, then ten consecutive uncancelled
green pushes.

The security workflow enforces:

- hash-verified Python dependency audits for the application, Browser Use tool
  environment and CI tooling;
- Bandit medium/high-confidence SAST plus CodeQL extended queries for Python,
  JavaScript/TypeScript, and GitHub Actions;
- full-history Gitleaks scanning and actionlint;
- high/critical Trivy IaC checks from a digest-pinned image using its embedded
  policy bundle, so the gate needs no credentials or mutable policy download;
- builds of kernel, fleet, UI, and backup images;
- a CycloneDX SBOM and complete high/critical Trivy JSON report for every image;
- a blocking container gate for every high/critical advisory with an available
  fix.

The complete Trivy report intentionally retains unfixed advisories as a 30-day
artifact. The blocking leg uses `ignore-unfixed` because there is no deployable
remediation for those records; this is a triage state, not a blanket allowlist.
Any newly available fix turns the gate red automatically. Accepted exceptions
must still record reachability, owner, expiry, and compensating control; do not
add a repository-wide CVE baseline.

Gitleaks exceptions in `.gitleaks.toml` are restricted by rule, exact test path,
and exact synthetic fixture. They exist only for tests that prove Boltrig rejects
or redacts those secret shapes. Never allowlist a directory, a whole rule, or a
production path.

Run the source gates locally with `make security-source`; `make quality` includes
them with the backend, frontend, browser, doctor, Compose, coverage, and migration
gates.

A protected semantic tag triggers `.github/workflows/release.yml`. Before it
creates a draft GitHub release, the workflow proves the exact commit has canonical
CI and security success. For each of the kernel, fleet, UI, and backup
images it then:

1. requires the tagged commit to be reachable from the default branch and the
   latest `ci.yml` and `security.yml` workflow runs for that exact SHA to have
   completed successfully;
2. rebuilds locally and blocks fixable high/critical findings;
3. pushes only a run-scoped candidate tag and records its immutable digest;
4. signs that digest with Sigstore/Cosign and the workflow's GitHub OIDC identity;
5. attaches a signed CycloneDX SBOM attestation and pinned `actions/attest` SLSA
   provenance bound to the exact repository workflow, tag, and source commit;
6. verifies the signature, SBOM attestation, and provenance; and
7. retains the SBOM, provenance bundle, and digest as Actions evidence and
   draft-release assets.

Only after all four candidates verify does the workflow reverify every digest,
refuse to move any existing release or commit tag, promote those exact digests to
their public tags, and publish the GitHub release. A failed run therefore never
publishes an incomplete GitHub release or an unsigned official image. Evidence
is never overwritten; if a run leaves a draft behind, investigate it and delete
the draft explicitly before creating a replacement release.

The published release also contains `boltrig-images.env`: exactly four
`BOLTRIG_*_IMAGE` variables whose values are the verified `image@sha256` refs.
`deploy/compose.release.yml` removes every first-party `build` key and requires
those values; both fleet-worker entry points, including the durable Hatchet task
server, use the same signed fleet digest. `scripts/validate_release_images.py`
rejects missing, extra, or mutable image references. Download the environment
beside a production `.env`, run `make release-validate`, then `make release-up`;
the latter layers the release overlay under the secure overlay, enables the
backup profile, pulls the four signed images, and starts with `--no-build`.
`release-validate` is deliberately online and fail-closed: with Cosign and a
GitHub CLI that supports `gh attestation verify` installed, it verifies every
registry digest's release-workflow certificate, CycloneDX attestation, and OCI
SLSA provenance against `wlilley93/boltrig`, `release.yml`, the exact semantic
tag on the checkout, and that checkout's commit. Missing tools, evidence, tags,
or network access are blockers; digest syntax alone never admits production.

Configure the GitHub `release` environment with required reviewers, restrict who
may create `vMAJOR.MINOR.PATCH` tags, and require the `ci / quality` and
`security / Security gate` checks on `main`. Those repository settings are an
external enforcement step; the workflow cannot safely grant its own reviewers or
branch/tag protection. Production manifests must pin the recorded `@sha256:`
reference, never a mutable release tag, and admission/deploy automation must
verify the certificate identity for this repository's `release.yml` workflow.
