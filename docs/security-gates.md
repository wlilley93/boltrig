# Security gates

Boltrig has two stable CI checks intended for branch protection: `ci / quality`
and `security / Security gate`. Both must be successful before merge.

The security workflow enforces:

- hash-verified Python dependency audits for the application, Browser Use tool
  environment, Pi sidecar, and CI tooling;
- Bandit medium/high-confidence SAST plus CodeQL extended queries for Python,
  JavaScript/TypeScript, and GitHub Actions;
- full-history Gitleaks scanning and actionlint;
- builds of kernel, fleet, UI, Pi-sidecar, and backup images;
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

A protected semantic tag triggers `.github/workflows/release.yml`. The workflow
first creates a draft GitHub release. For each of the kernel, fleet, UI,
Pi-sidecar, and backup images it then:

1. requires the tagged commit to be reachable from the default branch;
2. rebuilds locally and blocks fixable high/critical findings;
3. pushes only a run-scoped candidate tag and records its immutable digest;
4. signs that digest with Sigstore/Cosign and the workflow's GitHub OIDC identity;
5. attaches a signed CycloneDX SBOM attestation and verifies both the signature
   and attestation; and
6. retains the SBOM and digest as Actions evidence and draft-release assets.

Only after all five candidates verify does the workflow reverify every digest,
refuse to move any existing release or commit tag, promote those exact digests to
their public tags, and publish the GitHub release. A failed run therefore never
publishes an incomplete GitHub release or an unsigned official image. Evidence
is never overwritten; if a run leaves a draft behind, investigate it and delete
the draft explicitly before creating a replacement release.

Configure the GitHub `release` environment with required reviewers, restrict who
may create `vMAJOR.MINOR.PATCH` tags, and require the `ci / quality` and
`security / Security gate` checks on `main`. Those repository settings are an
external enforcement step; the workflow cannot safely grant its own reviewers or
branch/tag protection. Production manifests must pin the recorded `@sha256:`
reference, never a mutable release tag, and admission/deploy automation must
verify the certificate identity for this repository's `release.yml` workflow.
