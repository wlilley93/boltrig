"""Signed desktop update-manifest release regressions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.build_desktop_update_manifest import build_fragment, merge_fragments

_REPOSITORY = "wlilley93/boltrig"
_TAG = "v1.2.3"
_COMMIT = "a" * 40
_SIGNATURE = "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo="


def _signed_package(bundle: Path, relative: str, content: bytes) -> Path:
    package = bundle / relative
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_bytes(content)
    package.with_name(f"{package.name}.sig").write_text(f"{_SIGNATURE}\n", encoding="utf-8")
    return package


def _fragments(tmp_path: Path) -> list[Path]:
    specifications = {
        "linux-x86_64": [("appimage/Boltrig.Worker.AppImage", b"linux")],
        "darwin-aarch64": [("macos/Boltrig Worker.app.tar.gz", b"mac")],
        "windows-x86_64": [
            ("msi/Boltrig Worker.msi", b"msi"),
            ("nsis/Boltrig Worker-setup.exe", b"nsis"),
        ],
    }
    fragments = []
    for platform, packages in specifications.items():
        bundle = tmp_path / platform
        for relative, content in packages:
            _signed_package(bundle, relative, content)
        fragment = build_fragment(
            platform=platform,
            bundle=bundle,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
        )
        path = tmp_path / f"desktop-update-{platform}.json"
        path.write_text(json.dumps(fragment), encoding="utf-8")
        fragments.append(path)
    return fragments


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_manifest_covers_each_installer_with_release_bound_urls(
    tmp_path: Path,
) -> None:
    manifest = merge_fragments(
        fragment_paths=_fragments(tmp_path),
        repository=_REPOSITORY,
        tag=_TAG,
        commit=_COMMIT,
        published_at="2026-08-14T08:00:00+00:00",
    )

    assert manifest["version"] == "1.2.3"
    assert manifest["pub_date"] == "2026-08-14T08:00:00+00:00"
    assert set(manifest["platforms"]) == {
        "linux-x86_64",
        "linux-x86_64-appimage",
        "darwin-aarch64",
        "darwin-aarch64-app",
        "windows-x86_64",
        "windows-x86_64-msi",
        "windows-x86_64-nsis",
    }
    for release in manifest["platforms"].values():
        assert release["signature"] == _SIGNATURE
        assert release["url"].startswith(
            f"https://github.com/{_REPOSITORY}/releases/download/{_TAG}/"
        )
        assert " " not in release["url"]
    assert manifest["platforms"]["windows-x86_64"]["url"].endswith("Boltrig%20Worker-setup.exe")


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_fragment_requires_every_signed_updater_package(tmp_path: Path) -> None:
    bundle = tmp_path / "windows"
    _signed_package(bundle, "msi/Boltrig Worker.msi", b"msi")

    with pytest.raises(ValueError, match="windows-x86_64-nsis"):
        build_fragment(
            platform="windows-x86_64",
            bundle=bundle,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
        )

    orphan = bundle / "nsis" / "Boltrig Worker-setup.exe.sig"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text(_SIGNATURE, encoding="utf-8")
    with pytest.raises(ValueError, match="has no package"):
        build_fragment(
            platform="windows-x86_64",
            bundle=bundle,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
        )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_manifest_refuses_missing_or_mixed_release_fragments(
    tmp_path: Path,
) -> None:
    fragments = _fragments(tmp_path)
    with pytest.raises(ValueError, match="every shipped target"):
        merge_fragments(
            fragment_paths=fragments[:2],
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
            published_at="2026-08-14T08:00:00Z",
        )

    tampered = json.loads(fragments[-1].read_text(encoding="utf-8"))
    tampered["commit"] = "b" * 40
    fragments[-1].write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(ValueError, match="identity mismatch"):
        merge_fragments(
            fragment_paths=fragments,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
            published_at="2026-08-14T08:00:00Z",
        )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_fragment_refuses_duplicate_packages_for_one_target(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "linux"
    _signed_package(bundle, "one/Boltrig.AppImage", b"one")
    _signed_package(bundle, "two/Boltrig.AppImage", b"two")
    with pytest.raises(ValueError, match="multiple updater packages"):
        build_fragment(
            platform="linux-x86_64",
            bundle=bundle,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
        )


@pytest.mark.security
@pytest.mark.invariant("IAC-005")
def test_desktop_fragment_refuses_symlinked_release_inputs(tmp_path: Path) -> None:
    bundle = tmp_path / "linux"
    package = _signed_package(bundle, "real/Boltrig.AppImage", b"package")
    signature = package.with_name(f"{package.name}.sig")
    signature.unlink()
    outside = tmp_path / "outside.sig"
    outside.write_text(_SIGNATURE, encoding="utf-8")
    signature.symlink_to(outside)

    with pytest.raises(ValueError, match="signature must not be a symlink"):
        build_fragment(
            platform="linux-x86_64",
            bundle=bundle,
            repository=_REPOSITORY,
            tag=_TAG,
            commit=_COMMIT,
        )
