"""Adversarial tests for immutable GitHub release-asset retry handling."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess

import pytest


_REPO = Path(__file__).resolve().parents[2]
_HELPER = _REPO / "scripts" / "release_asset.sh"
_DIGEST = "1" * 64
_IMAGE = f"ghcr.io/wlilley93/boltrig-kernel@sha256:{_DIGEST}"


def _executable(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n")
    path.chmod(0o755)


def _fake_tools(tmp_path: Path, *, statement: dict | None = None) -> Path:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _executable(
        fake_bin,
        "gh",
        """
if [[ "$1" == api ]]; then
  if [[ "$*" == *'/releases/assets/'* ]]; then
    cat "$FAKE_REMOTE_ASSET"
  else
    cat "$FAKE_RELEASE_JSON"
  fi
elif [[ "$1 $2" == 'release upload' ]]; then
  printf '%s\n' "$4" >> "$FAKE_UPLOAD_LOG"
  exit 70
elif [[ "$1 $2" == 'attestation verify' ]]; then
  [[ "${FAKE_PROVENANCE_VALID:-1}" == 1 ]] || exit 71
  args=" $* "
  for expected in \
    " --repo $GITHUB_REPOSITORY " \
    " --signer-workflow $GITHUB_REPOSITORY/.github/workflows/release.yml " \
    " --source-digest $RELEASE_COMMIT " \
    " --source-ref refs/tags/$RELEASE_TAG " \
    " --predicate-type https://slsa.dev/provenance/v1 "
  do
    [[ "$args" == *"$expected"* ]] || exit 73
  done
else
  echo "unexpected gh call: $*" >&2
  exit 72
fi
""".strip(),
    )
    payload = ""
    if statement is not None:
        payload = base64.b64encode(
            json.dumps(statement, separators=(",", ":")).encode()
        ).decode()
    _executable(
        fake_bin,
        "cosign",
        f"""
args=" $* "
for expected in \\
  " --type cyclonedx " \\
  " --output json " \\
  " --certificate-identity $CERTIFICATE_IDENTITY " \\
  " --certificate-oidc-issuer $CERTIFICATE_ISSUER " \\
  " --certificate-github-workflow-repository $GITHUB_REPOSITORY " \\
  " --certificate-github-workflow-ref refs/tags/$RELEASE_TAG " \\
  " --certificate-github-workflow-sha $RELEASE_COMMIT "
do
  [[ "$args" == *"$expected"* ]] || exit 74
done
printf '%s\\n' '{json.dumps({'payload': payload})}'
""".strip(),
    )
    return fake_bin


def _release(tmp_path: Path, asset_name: str, *, draft: bool = True) -> Path:
    path = tmp_path / "release.json"
    path.write_text(
        json.dumps(
            {
                "id": 7,
                "tag_name": "v1.2.3",
                "draft": draft,
                "assets": [{"id": 42, "name": asset_name}],
            }
        )
    )
    return path


def _run(
    tmp_path: Path,
    mode: str,
    local: Path,
    remote: Path,
    *,
    statement: dict | None = None,
    draft: bool = True,
    provenance_valid: bool = True,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    fake_bin = _fake_tools(tmp_path, statement=statement)
    upload_log = tmp_path / "uploads.log"
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_RELEASE_JSON": str(_release(tmp_path, local.name, draft=draft)),
        "FAKE_REMOTE_ASSET": str(remote),
        "FAKE_UPLOAD_LOG": str(upload_log),
        "FAKE_PROVENANCE_VALID": "1" if provenance_valid else "0",
        "GITHUB_REPOSITORY": "wlilley93/boltrig",
        "RELEASE_ID": "7",
        "RELEASE_TAG": "v1.2.3",
        "RELEASE_COMMIT": "a" * 40,
        "CERTIFICATE_IDENTITY": (
            "https://github.com/wlilley93/boltrig/.github/workflows/"
            "release.yml@refs/tags/v1.2.3"
        ),
        "CERTIFICATE_ISSUER": "https://token.actions.githubusercontent.com",
    }
    return subprocess.run(
        [_HELPER, mode, local, _IMAGE],
        cwd=_REPO,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_exact_asset_retry_reuses_bytes_and_refuses_replacement(tmp_path: Path) -> None:
    local = tmp_path / "image-ref-kernel.txt"
    remote = tmp_path / "remote.txt"
    local.write_text(f"{_IMAGE}\n")
    remote.write_bytes(local.read_bytes())

    accepted = _run(tmp_path / "accepted", "exact", local, remote)
    assert accepted.returncode == 0, accepted.stderr
    assert "reused immutable release asset" in accepted.stdout

    remote.write_text("attacker-controlled replacement\n")
    refused = _run(tmp_path / "refused", "exact", local, remote)
    assert refused.returncode != 0
    assert "differs from this run" in refused.stderr


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_semantic_sbom_retry_requires_the_verified_digest_predicate(
    tmp_path: Path,
) -> None:
    sbom = {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1}
    local = tmp_path / "sbom-kernel.cdx.json"
    remote = tmp_path / "remote.json"
    local.write_text(json.dumps(sbom))
    remote.write_text(json.dumps(sbom, indent=2))
    statement = {
        "subject": [{"digest": {"sha256": _DIGEST}}],
        "predicate": sbom,
    }

    accepted = _run(
        tmp_path / "accepted", "cyclonedx", local, remote, statement=statement
    )
    assert accepted.returncode == 0, accepted.stderr

    remote.write_text(
        json.dumps({"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 2})
    )
    refused = _run(
        tmp_path / "refused", "cyclonedx", local, remote, statement=statement
    )
    assert refused.returncode != 0
    assert "not the predicate of a trusted attestation" in refused.stderr


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_provenance_and_release_state_fail_closed(tmp_path: Path) -> None:
    local = tmp_path / "provenance-kernel.intoto.json"
    remote = tmp_path / "remote.json"
    local.write_text('{"bundle":"new-run"}')
    remote.write_text('{"bundle":"prior-run"}')

    accepted = _run(
        tmp_path / "accepted-provenance", "provenance", local, remote
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "reused immutable release asset" in accepted.stdout

    bad_provenance = _run(
        tmp_path / "bad-provenance",
        "provenance",
        local,
        remote,
        provenance_valid=False,
    )
    assert bad_provenance.returncode != 0

    published = _run(
        tmp_path / "published", "exact", local, remote, draft=False
    )
    assert published.returncode != 0
    assert "not the expected unpublished draft" in published.stderr
