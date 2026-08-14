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

from scripts.validate_release_mode import validate_release_mode

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
@pytest.mark.parametrize(
    "mode",
    ("", "CORE", " core", "full ", "core,full", "desktop", "false"),
)
def test_release_mode_rejects_missing_or_ambiguous_values(mode: str) -> None:
    with pytest.raises(ValueError, match="must be set explicitly"):
        validate_release_mode(mode)


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
@pytest.mark.parametrize("mode", ("core", "full"))
def test_release_mode_accepts_only_the_two_exact_postures(mode: str) -> None:
    assert validate_release_mode(mode) == mode


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_core_release_is_explicit_and_keeps_all_server_evidence() -> None:
    preflight = _WORKFLOW["jobs"]["preflight"]
    assert preflight["env"]["RELEASE_MODE"] == "${{ vars.BOLTRIG_RELEASE_MODE }}"
    mode_step = _step("preflight", "Require one explicit protected release mode")
    assert "scripts/validate_release_mode.py" in mode_step["run"]
    assert preflight["outputs"]["release-mode"] == (
        "${{ steps.release-mode.outputs.release-mode }}"
    )

    candidates = _WORKFLOW["jobs"]["candidates"]
    images = {entry["image"] for entry in candidates["strategy"]["matrix"]["include"]}
    assert images == {"kernel", "fleet", "worker-ui", "backup"}

    desktop = _WORKFLOW["jobs"]["desktop-candidates"]
    assert desktop["if"] == "${{ needs.preflight.outputs.release-mode == 'full' }}"
    publish = _WORKFLOW["jobs"]["publish"]
    publish_condition = str(publish["if"])
    assert "needs.candidates.result == 'success'" in publish_condition
    assert "needs.preflight.outputs.release-mode == 'core'" in publish_condition

    evidence = _step("publish", "Download and validate all draft release evidence")["run"]
    for required in (
        "image-ref-*.txt",
        "sbom-*.cdx.json",
        "provenance-*.intoto.json",
        'test "$(find release-evidence -name \'image-ref-*.txt\' -type f | wc -l)" -eq 4',
        'test "$(find release-evidence -name \'sbom-*.cdx.json\' -type f | wc -l)" -eq 4',
        'test "$(find release-evidence -name \'provenance-*.intoto.json\' -type f | wc -l)" -eq 4',
    ):
        assert required in evidence
    assert 'test "$desktop_count" -eq 0' in evidence
    assert "$RELEASE_MODE release draft contains an unexpected asset" in evidence
    assert "select(($allowed | index($name)) == null)" in evidence
    for server_asset in (
        "release-metadata.json",
        "image-ref-kernel.txt",
        "image-ref-fleet.txt",
        "image-ref-worker-ui.txt",
        "image-ref-backup.txt",
        "sbom-kernel.cdx.json",
        "sbom-fleet.cdx.json",
        "sbom-worker-ui.cdx.json",
        "sbom-backup.cdx.json",
        "provenance-kernel.intoto.json",
        "provenance-fleet.intoto.json",
        "provenance-worker-ui.intoto.json",
        "provenance-backup.intoto.json",
    ):
        assert f'"{server_asset}"' in evidence


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_full_release_still_requires_every_desktop_candidate() -> None:
    publish = _WORKFLOW["jobs"]["publish"]
    assert "desktop-candidates" in publish["needs"]
    assert "needs.desktop-candidates.result == 'success'" in str(publish["if"])

    evidence = _step("publish", "Download and validate all draft release evidence")["run"]
    assert "if [ \"$RELEASE_MODE\" = full ]; then" in evidence
    assert "--pattern 'desktop-evidence-*.txt'" in evidence
    assert "--pattern 'desktop-update-*.json'" in evidence
    assert 'test "$desktop_count" -eq 3' in evidence
    assert 'test "$desktop_fragment_count" -eq 3' in evidence
    assert "build_desktop_update_manifest.py merge" in evidence
    assert "release-evidence/latest.json" in evidence
    for platform in ("linux-x86_64", "darwin-aarch64", "windows-x86_64"):
        assert platform in evidence

    final = _step("release", "Require a fully published signed release")["run"]
    assert 'full) test "$DESKTOP_CANDIDATES_RESULT" = success' in final
    assert 'core) test "$DESKTOP_CANDIDATES_RESULT" = skipped' in final


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_release_metadata_binds_mode_and_closed_runtime_admissions() -> None:
    preflight = _WORKFLOW["jobs"]["preflight"]
    assert preflight["outputs"]["release-id"] == "${{ steps.draft.outputs.release-id }}"
    binding = _step("preflight", "Bind draft metadata")["run"]
    binding_env = _step("preflight", "Bind draft metadata")["env"]
    assert binding_env["RELEASE_ID"] == "${{ steps.draft.outputs.release-id }}"
    assert 'mode: $mode' in binding
    assert 'desktop: $desktop' in binding
    assert 'hosted_agent: $hosted_agent' in binding
    assert 'local_desktop_agent: $local_desktop_agent' in binding
    assert 'channels: "disabled"' in binding
    assert "release-metadata.json" in binding
    assert "cmp -s" in binding
    assert "--clobber" not in binding
    assert "unbound draft already contains assets; refusing adoption" in binding
    assert 'releases/$RELEASE_ID' in binding

    evidence = _step("publish", "Download and validate all draft release evidence")["run"]
    assert ".admissions.hosted_agent" in evidence
    assert ".admissions.local_desktop_agent" in evidence
    assert '.admissions.channels == "disabled"' in evidence
    assert '.mode == $mode' in evidence


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


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_candidates_embed_the_protected_api_origin() -> None:
    desktop = _WORKFLOW["jobs"]["desktop-candidates"]
    configured = str(desktop["env"]["BOLTRIG_DESKTOP_API_ORIGIN"])
    assert desktop["environment"] == "release"
    assert configured == "${{ vars.BOLTRIG_DESKTOP_API_ORIGIN }}"
    assert "secrets." not in configured

    requirement = _step("desktop-candidates", "Require protected API")["run"]
    assert "BOLTRIG_DESKTOP_API_ORIGIN" in requirement
    assert 'origin.protocol !== "https:"' in requirement
    assert 'raw !== canonical' in requirement
    assert 'hostname.endsWith(".boltrig.io")' in requirement

    build = _step("desktop-candidates", "Build signed installers")
    assert build["env"]["VITE_API_BASE"] == (
        "${{ env.BOLTRIG_DESKTOP_API_ORIGIN }}"
    )
    proof = _step("desktop-candidates", "Verify the packaged frontend")
    assert proof["env"]["VITE_API_BASE"] == build["env"]["VITE_API_BASE"]
    assert "find dist" in proof["run"]
    assert 'grep -RFl --include=\'*.js\' -- "$VITE_API_BASE" dist' in proof["run"]


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_full_release_bakes_only_a_reviewed_desktop_download_into_worker() -> None:
    candidates = _WORKFLOW["jobs"]["candidates"]
    assert candidates["env"]["RELEASE_MODE"] == (
        "${{ needs.preflight.outputs.release-mode }}"
    )
    assert candidates["env"]["BOLTRIG_DESKTOP_DOWNLOAD_URL"] == (
        "${{ vars.BOLTRIG_DESKTOP_DOWNLOAD_URL }}"
    )
    build = _step("candidates", "Build release candidate locally")["run"]
    assert 'if [ "$IMAGE" = worker-ui ]' in build
    assert 'if [ "$RELEASE_MODE" = full ]' in build
    assert 'parsed.scheme != "https"' in build
    assert 'parsed.username is not None' in build
    assert '--build-arg "VITE_DESKTOP_DOWNLOAD_URL=$desktop_download_url"' in build

    dockerfile = (_REPO / "apps" / "worker" / "Dockerfile").read_text()
    assert 'ARG VITE_DESKTOP_DOWNLOAD_URL=""' in dockerfile
    assert "ENV VITE_DESKTOP_DOWNLOAD_URL=${VITE_DESKTOP_DOWNLOAD_URL}" in dockerfile


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_release_reruns_reuse_only_the_exact_unpublished_draft() -> None:
    step = _step("preflight", "Create or reuse only the exact draft")
    run = step["run"]
    assert step["env"]["RELEASE_COMMIT"] == "${{ steps.verify.outputs.release-commit }}"
    assert step["id"] == "draft"
    assert "--paginate --slurp" in run
    assert ".tag_name == $tag" in run
    assert "releases/tags/$RELEASE_TAG" not in run
    assert "target_commitish" in run and "is_draft" in run
    assert 'if [ "$is_draft" != true ]; then' in run
    assert '"$DEFAULT_BRANCH"|"$RELEASE_COMMIT"' in run
    assert 'echo "release-id=$release_id" >> "$GITHUB_OUTPUT"' in run
    assert '--target "$RELEASE_COMMIT"' in run
    assert run.index('if [ "$is_draft" != true ]; then') < run.index("using draft")
    assert "--clobber" not in _TEXT


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_candidate_retry_reuses_only_the_new_builds_exact_digest() -> None:
    build = _step("candidates", "Build release candidate locally")["run"]
    push = _step("candidates", "Push only a run-scoped candidate")["run"]

    assert '--metadata-file "$BUILD_METADATA_FILE"' in build
    assert '."containerimage.digest" // empty' in push
    assert 'if [ "$existing_digest" != "$expected_digest" ]; then' in push
    assert 'reusing exact candidate $candidate_ref@$expected_digest' in push
    assert "404)" in push and 'docker push "$candidate_ref"' in push
    assert 'if [ "$digest" != "$expected_digest" ]; then' in push
    assert push.index('if [ "$existing_digest" != "$expected_digest" ]; then') < (
        push.index('docker push "$candidate_ref"')
    )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_fixed_release_assets_are_read_back_without_replacement() -> None:
    attach = _step("candidates", "Attach immutable evidence")["run"]
    desktop = _step("desktop-candidates", "Attach signed desktop packages")["run"]
    compose = _step("publish", "Attach the digest-pinned Compose environment")["run"]
    latest = _step("publish", "Attach the signed desktop update manifest")["run"]

    assert 'release_asset.sh exact "$IMAGE_REF_FILE"' in attach
    assert 'release_asset.sh cyclonedx "$SBOM_FILE" "$IMAGE_REF"' in attach
    assert 'release_asset.sh provenance "$PROVENANCE_FILE" "$IMAGE_REF"' in attach
    assert 'release_asset.sh exact "$asset"' in desktop
    assert 'release_asset.sh exact "$fragment"' in desktop
    assert 'release_asset.sh exact "$evidence"' in desktop
    assert "release_asset.sh exact release-evidence/boltrig-images.env" in compose
    assert "release_asset.sh exact release-evidence/latest.json" in latest
    assert "--clobber" not in _TEXT
    assert "release delete-asset" not in _TEXT


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_updater_uses_the_manifest_this_workflow_atomically_publishes() -> None:
    desktop = _WORKFLOW["jobs"]["desktop-candidates"]
    assert desktop["env"]["BOLTRIG_UPDATER_ENDPOINT"] == (
        "https://github.com/${{ github.repository }}/releases/latest/download/latest.json"
    )
    requirement = _step("desktop-candidates", "Require protected API")["run"]
    assert "expected_updater_endpoint" in requirement
    assert '"$BOLTRIG_UPDATER_ENDPOINT" != "$expected_updater_endpoint"' in requirement

    package = _step("desktop-candidates", "Attach signed desktop packages")["run"]
    assert "build_desktop_update_manifest.py fragment" in package
    assert '--platform "$PLATFORM"' in package
    assert '--commit "$RELEASE_COMMIT"' in package

    publish = _step("publish", "Publish the fully verified GitHub release")["run"]
    assert "latest=(--latest=false)" in publish
    assert 'elif [ "$RELEASE_MODE" = full ]; then' in publish
    assert "latest=(--latest)" in publish
    assert '[[ "$RELEASE_TAG" == *-* ]]' in publish


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_partial_publication_reuses_exact_tags_and_refuses_mismatches() -> None:
    preflight = _step(
        "publish", "Require existing public image tags to match expected digests"
    )["run"]
    promote = _step("publish", "Promote verified digests")["run"]

    assert 'if [ "$existing_digest" != "$digest" ]; then' in preflight
    assert "reusing exact immutable public tag" in preflight
    assert "404) ;;" in preflight
    assert "-X PUT" not in preflight

    assert 'if [ "$existing_digest" != "$digest" ]; then' in promote
    assert "leaving exact immutable public tag" in promote
    assert "404)" in promote and "-X PUT" in promote
    exact_branch = promote.split("200)", 1)[1].split("404)", 1)[0]
    assert "-X PUT" not in exact_branch
    assert 'test "$promoted_digest" = "$digest"' in promote
