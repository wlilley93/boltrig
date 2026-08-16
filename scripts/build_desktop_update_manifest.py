"""Build and merge immutable Tauri desktop-update release fragments."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

_FRAGMENT_SCHEMA = "boltrig.desktop-update-fragment/v1"
_SEMANTIC_TAG = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SIGNATURE = re.compile(r"^[A-Za-z0-9+/=]+$")
_PLATFORMS = frozenset({"linux-x86_64", "darwin-aarch64", "windows-x86_64"})
_REQUIRED_TARGETS = frozenset(
    {
        "linux-x86_64",
        "linux-x86_64-appimage",
        "darwin-aarch64",
        "darwin-aarch64-app",
        "windows-x86_64",
        "windows-x86_64-msi",
        "windows-x86_64-nsis",
    }
)


def _require_release_identity(tag: str, commit: str, repository: str) -> None:
    if not _SEMANTIC_TAG.fullmatch(tag):
        raise ValueError("desktop update tag must be an exact semantic release tag")
    if not _COMMIT.fullmatch(commit):
        raise ValueError("desktop update commit must be one lowercase Git commit id")
    if not _REPOSITORY.fullmatch(repository):
        raise ValueError("desktop update repository must be OWNER/REPOSITORY")


def _signature_text(path: Path) -> str:
    try:
        value = "".join(path.read_text(encoding="utf-8").split())
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read updater signature {path.name}") from exc
    if len(value) < 16 or len(value) > 16_384 or not _SIGNATURE.fullmatch(value):
        raise ValueError(f"updater signature {path.name} is not bounded base64 text")
    return value


def _artifact_for_signature(signature: Path) -> Path:
    if signature.suffix != ".sig":
        raise ValueError(f"updater signature has an unexpected name: {signature.name}")
    if signature.is_symlink():
        raise ValueError(f"updater signature must not be a symlink: {signature.name}")
    artifact = signature.with_suffix("")
    if not artifact.is_file():
        raise ValueError(f"updater signature has no package: {signature.name}")
    if artifact.is_symlink():
        raise ValueError(f"updater package must not be a symlink: {artifact.name}")
    if artifact.name in {"", ".", ".."} or any(ord(character) < 32 for character in artifact.name):
        raise ValueError("updater package has an unsafe release asset name")
    return artifact


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _release_url(repository: str, tag: str, asset: Path) -> str:
    return f"https://github.com/{repository}/releases/download/{tag}/{quote(asset.name, safe='')}"


def _platform_packages(platform: str, bundle: Path) -> dict[str, Path]:
    signatures = sorted(bundle.rglob("*.sig"))
    packages: dict[str, Path] = {}
    for signature in signatures:
        artifact = _artifact_for_signature(signature)
        name = artifact.name.lower()
        target = None
        if platform == "linux-x86_64" and name.endswith(".appimage"):
            target = "linux-x86_64-appimage"
        elif platform == "darwin-aarch64" and name.endswith(".app.tar.gz"):
            target = "darwin-aarch64-app"
        elif platform == "windows-x86_64" and name.endswith(".msi"):
            target = "windows-x86_64-msi"
        elif platform == "windows-x86_64" and name.endswith("-setup.exe"):
            target = "windows-x86_64-nsis"
        if target is not None:
            if target in packages:
                raise ValueError(f"multiple updater packages match {target}")
            packages[target] = signature

    expected = {
        "linux-x86_64": {"linux-x86_64-appimage"},
        "darwin-aarch64": {"darwin-aarch64-app"},
        "windows-x86_64": {
            "windows-x86_64-msi",
            "windows-x86_64-nsis",
        },
    }[platform]
    if set(packages) != expected:
        missing = ", ".join(sorted(expected - set(packages))) or "none"
        raise ValueError(f"{platform} updater packages are incomplete (missing: {missing})")
    return packages


def build_fragment(
    *,
    platform: str,
    bundle: Path,
    repository: str,
    tag: str,
    commit: str,
) -> dict[str, Any]:
    """Project one platform's signed Tauri packages into an immutable fragment."""
    _require_release_identity(tag, commit, repository)
    if platform not in _PLATFORMS:
        raise ValueError(f"unsupported desktop update platform: {platform}")
    if not bundle.is_dir():
        raise ValueError("desktop update bundle directory does not exist")

    signed_packages = _platform_packages(platform, bundle)
    platforms: dict[str, dict[str, str]] = {}
    assets: dict[str, dict[str, str]] = {}
    for target, signature_path in sorted(signed_packages.items()):
        artifact = _artifact_for_signature(signature_path)
        platforms[target] = {
            "signature": _signature_text(signature_path),
            "url": _release_url(repository, tag, artifact),
        }
        assets[target] = {
            "name": artifact.name,
            "sha256": _sha256_file(artifact),
        }

    preferred = {
        "linux-x86_64": "linux-x86_64-appimage",
        "darwin-aarch64": "darwin-aarch64-app",
        # The shipped NSIS installer is current-user scoped. Installed MSI copies
        # still select the explicit -msi entry before this base fallback.
        "windows-x86_64": "windows-x86_64-nsis",
    }[platform]
    platforms[platform] = dict(platforms[preferred])
    assets[platform] = dict(assets[preferred])
    return {
        "schema": _FRAGMENT_SCHEMA,
        "tag": tag,
        "commit": commit,
        "platform": platform,
        "platforms": platforms,
        "assets": assets,
    }


def _read_fragment(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read desktop update fragment {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"desktop update fragment {path.name} is not an object")
    return value


def _validate_published_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("desktop update publication date must be RFC 3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("desktop update publication date must include a timezone")
    return value


def merge_fragments(
    *,
    fragment_paths: list[Path],
    repository: str,
    tag: str,
    commit: str,
    published_at: str,
) -> dict[str, Any]:
    """Merge exactly three release-bound fragments into Tauri static JSON."""
    _require_release_identity(tag, commit, repository)
    platforms: dict[str, dict[str, str]] = {}
    seen_platforms: set[str] = set()
    for path in fragment_paths:
        fragment = _read_fragment(path)
        platform = fragment.get("platform")
        if (
            fragment.get("schema") != _FRAGMENT_SCHEMA
            or fragment.get("tag") != tag
            or fragment.get("commit") != commit
            or platform not in _PLATFORMS
            or platform in seen_platforms
        ):
            raise ValueError(f"desktop update fragment identity mismatch: {path.name}")
        fragment_platforms = fragment.get("platforms")
        fragment_assets = fragment.get("assets")
        if not isinstance(fragment_platforms, dict) or not isinstance(fragment_assets, dict):
            raise ValueError(f"desktop update fragment is incomplete: {path.name}")
        for target, release in fragment_platforms.items():
            if target in platforms or not isinstance(release, dict):
                raise ValueError(f"duplicate or invalid desktop target: {target}")
            url = release.get("url")
            signature = release.get("signature")
            asset = fragment_assets.get(target)
            if (
                not isinstance(url, str)
                or not isinstance(signature, str)
                or not isinstance(asset, dict)
                or not isinstance(asset.get("name"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(asset.get("sha256", "")))
            ):
                raise ValueError(f"desktop update target is incomplete: {target}")
            parsed = urlparse(url)
            expected_prefix = f"/{repository}/releases/download/{tag}/"
            if (
                parsed.scheme != "https"
                or parsed.netloc != "github.com"
                or not parsed.path.startswith(expected_prefix)
                or not _SIGNATURE.fullmatch(signature)
            ):
                raise ValueError(f"desktop update target is not release-bound: {target}")
            platforms[target] = {"signature": signature, "url": url}
        seen_platforms.add(str(platform))

    if seen_platforms != _PLATFORMS or set(platforms) != _REQUIRED_TARGETS:
        raise ValueError("desktop update manifest does not cover every shipped target")
    return {
        "version": tag.removeprefix("v"),
        "notes": f"Boltrig {tag}",
        "pub_date": _validate_published_at(published_at),
        "platforms": dict(sorted(platforms.items())),
    }


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    fragment = subparsers.add_parser("fragment")
    fragment.add_argument("--platform", required=True)
    fragment.add_argument("--bundle", type=Path, required=True)
    fragment.add_argument("--repository", required=True)
    fragment.add_argument("--tag", required=True)
    fragment.add_argument("--commit", required=True)
    fragment.add_argument("--output", type=Path, required=True)

    merge = subparsers.add_parser("merge")
    merge.add_argument("--repository", required=True)
    merge.add_argument("--tag", required=True)
    merge.add_argument("--commit", required=True)
    merge.add_argument("--published-at", required=True)
    merge.add_argument("--output", type=Path, required=True)
    merge.add_argument("fragments", type=Path, nargs="+")

    args = parser.parse_args()
    try:
        if args.command == "fragment":
            result = build_fragment(
                platform=args.platform,
                bundle=args.bundle,
                repository=args.repository,
                tag=args.tag,
                commit=args.commit,
            )
        else:
            result = merge_fragments(
                fragment_paths=args.fragments,
                repository=args.repository,
                tag=args.tag,
                commit=args.commit,
                published_at=args.published_at,
            )
        _write_json(args.output, result)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
