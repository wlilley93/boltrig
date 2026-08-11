"""The release workflow must be able to publish, and fail fast when it cannot (IAC-005).

`release.yml` has existed since 2026-07-13 and has run EXACTLY ONCE, on v0.4.11,
and that run failed. The promote step is the only thing in this repository that
creates `:MAJOR.MINOR.PATCH` image tags, so every image in production - 0.4.9,
0.4.11, 0.4.12 - was built and pushed by hand OUTSIDE the protected path: no Trivy
block, no cosign signature, no SBOM attestation, no digest reverification.

Three things stopped that run. Two were already fixed by #115 and are pinned here
so they cannot silently regress:

  * the former frontend candidate built with an EMPTY `gh_npmrc` secret mount and
    died on ERR_PNPM_FETCH_401;
  * the vulnerability gate read no `.trivyignore.yaml`, so it blocked on an
    advisory the security workflow already accepts with a written justification
    and an expiry. A release gate stricter than the security gate BY ACCIDENT is
    not a stricter policy, it is drift.

The third is not fixable in code, and that is the reason the preflight exists.
kernel and fleet are user-owned GHCR packages that predate this workflow, so
the repository's Actions token cannot write them. The same run proved it by
accident: `pi-sidecar`, the one package LINKED to the repository, pushed fine.
GitHub links a package by the `org.opencontainers.image.source` label only when the
push CREATES it - so an existing package cannot bootstrap its own access - and no
REST or GraphQL endpoint exposes the setting.

What CAN be fixed is the ten minutes wasted discovering it, and a message
(`denied: permission_denied: write_package`) that names neither cause nor remedy.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOW = yaml.safe_load((_REPO / ".github" / "workflows" / "release.yml").read_text())
_TEXT = (_REPO / ".github" / "workflows" / "release.yml").read_text()


def _steps(job: str) -> list[dict]:
    return _WORKFLOW["jobs"][job]["steps"]


def _step(job: str, prefix: str) -> dict:
    for step in _steps(job):
        if str(step.get("name", "")).startswith(prefix):
            return step
    raise AssertionError(f"no step in {job} named {prefix!r}")


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_registry_write_access_is_checked_before_the_builds() -> None:
    """Ordering is the whole value: after the builds this costs ten minutes."""
    preflight = [str(s.get("name", "")) for s in _steps("preflight")]
    assert any(n.startswith("Registry write access") for n in preflight), (
        "the release workflow no longer checks it can push before building"
    )
    # and it is in the job that runs FIRST, not alongside the candidates
    assert "preflight" in _WORKFLOW["jobs"]["candidates"]["needs"]


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_the_write_probe_creates_nothing() -> None:
    """A push-probe would create the package, with the wrong owner.

    That is precisely the defect being detected, so the probe must not be able to
    cause it. Opening a blob upload and cancelling it proves write access and
    leaves no tag, no layer and no package.
    """
    run = _step("preflight", "Registry write access")["run"]
    assert "blobs/uploads/" in run and "-X POST" in run
    assert "-X DELETE" in run, "the upload session is never cancelled"
    assert "docker push" not in run, (
        "the probe pushes, so a run against a missing package would CREATE it - "
        "the exact condition this check exists to report"
    )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_the_write_probe_can_actually_reach_its_own_output() -> None:
    """It could not. v0.4.14 died here twice, having proved the push WAS allowed.

    GitHub runs `run:` blocks under `bash --noprofile --norc -e -o pipefail`, and
    the step's own `set -uo pipefail` does not cancel that inherited `-e`. Two
    separate commands therefore aborted the step before any verdict was printed:

      * the registry returns `Location` as a PATH, not an absolute URL, so the
        cancel `curl` got a URL with no scheme and exited 3 - on the SUCCESS path,
        one line after HTTP 202 proved the package was writable;
      * on a genuine denial there is no `Location` header at all, so `grep` exited
        1, pipefail propagated it, and the assignment aborted - on the DENIAL path,
        before the branch that prints DENIED and the remedy.

    Success aborted and failure aborted, so this check had no path to its own
    output. Measured against the real script: with a bad credential the old
    version printed NOTHING, the fixed version prints four DENIED lines and the
    two-option remedy.
    """
    run = _step("preflight", "Registry write access")["run"]
    # The cancel URL must be absolutised before it reaches curl.
    assert 'cancel="https://ghcr.io$loc"' in run, (
        "Location is a path; curl exits 3 on it and bash -e kills the step"
    )
    # Cleanup is best effort: an abandoned upload session expires on its own, so it
    # must never be able to fail a release.
    assert "-X DELETE" in run and "|| true" in run.split("-X DELETE")[1][:200]
    # And the no-Location case must not abort before the DENIED branch.
    loc_line = next(ln for ln in run.splitlines() if ln.strip().startswith("loc="))
    assert loc_line.rstrip().endswith("|| true)\""), (
        f"no-match grep aborts under bash -e, so DENIED is unreachable: {loc_line.strip()}"
    )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_a_bad_credential_reports_the_remedy_rather_than_crashing() -> None:
    """The check must survive the case it exists for.

    An earlier cut piped the token response into a JSON parser. On a 401 the body
    is not JSON, so the step died with a stack trace instead of the explanation -
    at exactly the moment the explanation was needed.
    """
    run = _step("preflight", "Registry write access")["run"]
    assert "python3" not in run, "a JSON parser here dies on the 401 body"
    assert 'sed -n' in run
    for remedy in ("Manage Actions access", "GHCR_PUSH_TOKEN", "write:packages"):
        assert remedy in run, f"the failure message no longer names {remedy}"


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_every_registry_login_prefers_a_pat_when_one_exists() -> None:
    """So the remaining blocker closes by adding a secret, with no code change."""
    logins = [s for job in ("candidates", "publish") for s in _steps(job)
              if str(s.get("name", "")).startswith("Log in to GitHub Container Registry")]
    assert logins, "no registry login steps found"
    for step in logins:
        token = str(step["env"]["GHCR_TOKEN"])
        assert "GHCR_PUSH_TOKEN" in token and "GITHUB_TOKEN" in token, (
            f"a login uses only {token} - adding the PAT would not reach it"
        )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_the_release_vuln_gate_reads_the_same_acceptances_as_the_security_gate() -> None:
    """#115. Otherwise the two gates disagree about an identical image.

    2026-VJS-CC-BOLTRIG-SUPPLY-CHAIN-ADVISORY-ACCEPTANCE-001 D3: this pins the
    invocation the acceptance was proven against - the built backup image
    scanned with these exact args exits non-zero on CVE-2026-56852 with the
    .trivyignore.yaml entry removed and passes with it present (red/green runs
    recorded in the discharge note)."""
    step = _step("candidates", "Block fixable high or critical vulnerabilities")
    assert step["with"]["trivyignores"] == ".trivyignore.yaml"
    assert step["with"]["exit-code"] == "1"
    assert step["with"]["severity"] == "HIGH,CRITICAL"
    assert (_REPO / ".trivyignore.yaml").exists()


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_promotion_still_happens_only_after_every_candidate_is_verified() -> None:
    """The point of the preflight is to fail EARLIER, never to publish sooner."""
    publish = _WORKFLOW["jobs"]["publish"]
    assert "candidates" in publish["needs"]
    assert "cosign verify-attestation" in _TEXT
    promote = _step("publish", "Promote verified digests")
    assert _TEXT.index("cosign verify-attestation") < _TEXT.index(promote["name"])


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_promotion_publishes_the_exact_digest_that_was_signed() -> None:
    """v0.4.13, the first run ever to reach promotion, published an UNSIGNED digest.

    Candidates are published with `docker push`, so they are plain manifests.
    `docker buildx imagetools create` can only emit a manifest INDEX, so it wrapped
    the signed candidate `sha256:a9ee1707` in a new index `sha256:adb9b7d2` and
    put THAT on `:v0.4.13`. Same image content, but cosign signed a9ee1707, so the
    release tag resolved to bytes covered by no signature and no SBOM attestation.

    The step's own digest assertion caught it. This pins both halves of the repair:
    promotion must preserve the digest, and it must prove the bytes hash to the
    signed digest before it publishes them.
    """
    run = _step("publish", "Promote verified digests")["run"]
    assert "docker buildx imagetools create" not in run, (
        "imagetools cannot preserve a plain manifest's digest; it re-wraps it in an index"
    )
    assert 'test "$promoted_digest" = "$digest"' in run
    assert "sha256sum manifest.bin" in run
    assert 'if [ "$fetched" != "$digest" ]; then' in run
    # The integrity check must come before anything is written to a public tag.
    assert run.index('if [ "$fetched" != "$digest" ]; then') < run.index("-X PUT")
