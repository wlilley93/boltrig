#!/usr/bin/env python3
"""Stage one exact official Codex package for a signed Tauri build."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
# Used only to probe the exact digest-pinned release binary staged below.
import subprocess  # nosec B404
import tarfile
import tempfile
import urllib.request
from urllib.parse import urlsplit


VERSION = "0.144.3"
MAX_ARCHIVE_BYTES = 192 * 1024 * 1024
MAX_EXTRACTED_BYTES = 768 * 1024 * 1024

PLATFORMS = {
    "darwin-aarch64": {
        "archive_sha256": "d9779cc540a5dbe9ee7cf62bd2848962c26b8d5b6fbcbbb1389ccd0ff84fdb24",
        "binary_sha256": "718724d7221cf1298071ca92411cb74caa8422809154150cedca7b569a4518e3",
        "package_suffix": "darwin-arm64",
        "triple": "aarch64-apple-darwin",
        "binary": "codex",
    },
    "linux-x86_64": {
        "archive_sha256": "78366515c7e190cfa58712f6085c4fbc38be444d5ab49411f89026ce39653f2e",
        "binary_sha256": "37e6f5953f191b04f7b62cb07dae90f51d0947ad89f0355665b421fbde28700b",
        "package_suffix": "linux-x64",
        "triple": "x86_64-unknown-linux-musl",
        "binary": "codex",
    },
    "windows-x86_64": {
        "archive_sha256": "ead9e20b3dde4da30704d35a10e5a3b09f01e62103b66029788793383eca60f7",
        "binary_sha256": "e5dcc9f9b08102c58596af85345f689a69fd53a87d8d408bdc0fcdaf99fcf6e3",
        "package_suffix": "win32-x64",
        "triple": "x86_64-pc-windows-msvc",
        "binary": "codex.exe",
    },
}


class StageError(RuntimeError):
    """The release resource could not be proven exact."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(url: str, destination: Path) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "registry.npmjs.org"
        or parsed.port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise StageError("Codex package URL is outside the pinned registry origin")
    request = urllib.request.Request(
        url,
        headers={"Accept-Encoding": "identity", "User-Agent": "boltrig-release/1"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310  # noqa: S310
        if response.geturl() != url:
            raise StageError("Codex package redirected away from its pinned registry URL")
        declared = response.headers.get("Content-Length")
        if declared is None or not declared.isdigit():
            raise StageError("Codex package omitted an exact Content-Length")
        if int(declared) > MAX_ARCHIVE_BYTES:
            raise StageError("Codex package exceeds the archive ceiling")
        written = 0
        with destination.open("xb") as output:
            while chunk := response.read(min(1024 * 1024, MAX_ARCHIVE_BYTES + 1 - written)):
                written += len(chunk)
                if written > MAX_ARCHIVE_BYTES:
                    raise StageError("Codex package exceeded the archive ceiling")
                output.write(chunk)
        if written != int(declared):
            raise StageError("Codex package length changed in transit")


def _extract(archive: Path, destination: Path) -> None:
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for member in bundle.getmembers():
            relative = PurePosixPath(member.name)
            if not relative.parts or relative.parts[0] != "package":
                raise StageError("Codex package contains an unexpected root")
            relative = PurePosixPath(*relative.parts[1:])
            if not relative.parts:
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise StageError("Codex package contains an unsafe path")
            if not (member.isdir() or member.isfile()):
                raise StageError("Codex package contains a link or special file")
            target = destination.joinpath(*relative.parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if total > MAX_EXTRACTED_BYTES:
                raise StageError("Codex package exceeds the extracted-size ceiling")
            source = bundle.extractfile(member)
            if source is None:
                raise StageError("Codex package file could not be read")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            target.chmod(member.mode & 0o755)


def stage(platform: str, output: Path, archive: Path | None = None) -> dict[str, str]:
    spec = PLATFORMS.get(platform)
    if spec is None:
        raise StageError("unsupported desktop Codex platform")
    if output.exists():
        raise StageError("desktop Codex output already exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    version = f"{VERSION}-{spec['package_suffix']}"
    url = f"https://registry.npmjs.org/@openai/codex/-/codex-{version}.tgz"
    with tempfile.TemporaryDirectory(prefix=".codex-stage-", dir=output.parent) as raw:
        temporary = Path(raw)
        package = temporary / "codex.tgz"
        if archive is None:
            _download(url, package)
        else:
            if not archive.is_file() or archive.stat().st_size > MAX_ARCHIVE_BYTES:
                raise StageError("Codex package exceeds the archive ceiling")
            shutil.copyfile(archive, package)
        if _sha256(package) != spec["archive_sha256"]:
            raise StageError("Codex package digest mismatch")
        extracted = temporary / "codex"
        extracted.mkdir()
        _extract(package, extracted)
        binary = extracted / "vendor" / spec["triple"] / "bin" / spec["binary"]
        if not binary.is_file() or _sha256(binary) != spec["binary_sha256"]:
            raise StageError("Codex desktop binary digest mismatch")
        probe = subprocess.run(  # nosec B603
            [str(binary), "--version"],
            check=False,
            capture_output=True,
            env={},
            text=True,
            timeout=15,
        )
        if probe.returncode != 0 or probe.stdout.strip() != f"codex-cli {VERSION}":
            raise StageError("Codex desktop binary version probe failed")
        receipt = {
            "schema": "boltrig.desktop-codex/v1",
            "platform": platform,
            "version": VERSION,
            "source": url,
            "archive_sha256": spec["archive_sha256"],
            "binary_sha256": spec["binary_sha256"],
            "target": spec["triple"],
        }
        (extracted / "boltrig-desktop-codex.json").write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(extracted, output)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=sorted(PLATFORMS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    receipt = stage(args.platform, args.output, args.archive)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
